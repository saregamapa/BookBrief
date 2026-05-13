"""
Audio service: OpenRouter TTS (``OPENROUTER_TTS_MODEL``) + podcast script chat (``OPENROUTER_PODCAST_MODEL``);
optional Manus TTS fallback when OpenRouter TTS fails or key is unset.
"""
import io
import json
import logging
import re
import wave
from typing import List, Optional

from app.config import get_settings
from app.services.openrouter_client import get_openrouter_openai_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _clean_for_tts(text: str) -> str:
    """Strip Markdown syntax so TTS doesn't read out raw symbols."""
    # Remove headings markers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", text)
    # Remove inline code
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)
    # Remove links — keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Remove horizontal rules
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Remove bullet/numbered list markers
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _merge_wav_chunks(parts: List[bytes]) -> bytes:
    """Concatenate PCM from multiple WAV files (raw MP3 concat is invalid for decoders)."""
    bufs = [p for p in parts if p and len(p) > 44]
    if not bufs:
        return b""
    if len(bufs) == 1:
        return bufs[0]
    out = io.BytesIO()
    w_out: Optional[wave.Wave_write] = None
    ref: tuple[int, int, int] | None = None
    for raw in bufs:
        with wave.open(io.BytesIO(raw), "rb") as w_in:
            params = (w_in.getnchannels(), w_in.getsampwidth(), w_in.getframerate())
            if ref is None:
                ref = params
                w_out = wave.open(out, "wb")
                w_out.setnchannels(params[0])
                w_out.setsampwidth(params[1])
                w_out.setframerate(params[2])
            elif params != ref:
                if w_out is not None:
                    w_out.close()
                raise RuntimeError("TTS WAV chunks have mismatched format (cannot merge)")
            assert w_out is not None
            w_out.writeframes(w_in.readframes(w_in.getnframes()))
    if w_out is not None:
        w_out.close()
    return out.getvalue()


def _chunk_text(text: str, max_chars: int = 2400) -> List[str]:
    """Split text at sentence boundaries so each chunk ≤ max_chars."""
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    # Split on sentence-ending punctuation followed by whitespace
    sentences = re.split(r"(?<=[.!?])\s+", text)
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            # If a single sentence exceeds the limit, hard-split it
            if len(sentence) > max_chars:
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i : i + max_chars])
            else:
                current = sentence
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

def text_to_speech(text: str, voice: str = "onyx") -> bytes:
    """
    Convert text to speech audio bytes using OpenRouter TTS (primary) or Manus (fallback).

    Flow:
      1. If OPENROUTER_API_KEY is set → try OpenRouter ``/audio/speech``
         with ``OPENROUTER_TTS_MODEL`` (default: openai/gpt-4o-mini-tts).
         Long texts are chunked; multiple chunks use **WAV** and are merged into one WAV
         (concatenating MP3 binaries produces invalid audio).
      2. If OpenRouter TTS fails for any reason → fall through to Manus.
      3. If MANUS_API_KEY is set → try Manus TTS.
      4. If all fail → raise RuntimeError with the actual provider error included.
    """
    settings = get_settings()
    cleaned = _clean_for_tts(text)
    chunks = _chunk_text(cleaned)

    openrouter_exc: Optional[Exception] = None  # preserved for final error message

    # ── Primary: OpenRouter TTS ───────────────────────────────────────────────
    if (settings.openrouter_api_key or "").strip():
        from app.services import openrouter_tts

        api_key = (settings.openrouter_api_key or "").strip()

        # Model fallback chain: configured model → tts-1 (widely available)
        primary_model = settings.openrouter_tts_model
        fallback_models = ["openai/tts-1", "openai/tts-1-hd"]
        tts_candidates = [primary_model] + [m for m in fallback_models if m != primary_model]

        for tts_model in tts_candidates:
            logger.info(
                "openrouter_tts_start model=%s voice=%s chunks=%s",
                tts_model, voice, len(chunks),
            )
            try:
                audio_or: list[bytes] = []
                use_wav_merge = len(chunks) > 1
                response_fmt = (
                    "wav" if use_wav_merge else (settings.openrouter_tts_response_format or "mp3")
                )
                for i, chunk in enumerate(chunks):
                    if not chunk.strip():
                        continue
                    chunk_audio = openrouter_tts.synthesize_speech(
                        api_key,
                        chunk,
                        voice,
                        base_url=settings.openrouter_api_base,
                        model=tts_model,
                        response_format=response_fmt,
                        referer=settings.openrouter_http_referer,
                        timeout_seconds=float(settings.openrouter_tts_timeout_seconds),
                    )
                    audio_or.append(chunk_audio)
                    logger.debug(
                        "openrouter_tts_chunk_ok chunk=%s/%s bytes=%s",
                        i + 1, len(chunks), len(chunk_audio),
                    )
                if use_wav_merge:
                    merged_or = _merge_wav_chunks(audio_or)
                else:
                    merged_or = b"".join(audio_or)
                if len(merged_or) == 0:
                    raise RuntimeError("OpenRouter TTS returned zero audio bytes")
                logger.info(
                    "openrouter_tts_complete model=%s total_bytes=%s", tts_model, len(merged_or)
                )
                return merged_or
            except Exception as or_exc:
                openrouter_exc = or_exc  # preserve for error reporting below
                logger.warning(
                    "openrouter_tts_failed model=%s voice=%s err=%s — trying next model",
                    tts_model, voice, or_exc,
                )
                # Try next model in fallback chain

    # ── Fallback: Manus TTS ───────────────────────────────────────────────────
    if (settings.manus_api_key or "").strip():
        from app.services import manus_audio

        logger.info("manus_tts_start voice=%s chunks=%s", voice, len(chunks))
        audio_parts: List[bytes] = []
        manus_failed = False
        for chunk in chunks:
            if not chunk.strip():
                continue
            try:
                audio_parts.append(
                    manus_audio.synthesize_speech_chunk(
                        chunk,
                        voice,
                        settings.manus_api_key.strip(),
                        api_base=settings.manus_api_base,
                        timeout_seconds=float(settings.manus_tts_timeout_seconds),
                        agent_profile=settings.manus_agent_profile,
                    )
                )
            except Exception as manus_exc:
                logger.warning(
                    "manus_tts_chunk_failed chunk_len=%s voice=%s err=%s",
                    len(chunk), voice, manus_exc,
                )
                manus_failed = True
                break

        if not manus_failed:
            merged = b"".join(audio_parts)
            if len(merged) > 0:
                logger.info("manus_tts_complete total_bytes=%s", len(merged))
                return merged
            logger.warning("manus_tts_empty_result")

    # ── Build a helpful error that includes the real provider error ────────────
    or_detail = f" ({openrouter_exc})" if openrouter_exc else ""
    raise RuntimeError(
        f"TTS generation failed{or_detail}. "
        "Check your OPENROUTER_TTS_MODEL and API quota, "
        "or set MANUS_API_KEY as a fallback TTS provider."
    )


# ---------------------------------------------------------------------------
# Podcast script generation
# ---------------------------------------------------------------------------

_PODCAST_SYSTEM_PROMPT = """You are a scriptwriter for a book-discussion podcast called "Between the Pages".
The show has two hosts:
  • Alex — enthusiastic, asks probing questions, focuses on themes and meaning (voice: nova)
  • Jordan — analytical, provides deeper context, connects ideas to real life (voice: onyx)

Given a book summary, write an engaging 14–22-segment conversation (longer segments when the summary is rich).
Rules:
- Alternate between Alex and Jordan (start with Alex)
- Each segment: 1–3 natural-sounding sentences
- Do NOT say "in the summary" — discuss the book directly
- Use casual but intelligent language
- Include at least one moment of friendly disagreement
- End with Jordan giving a final takeaway

Respond ONLY with valid JSON matching this schema:
{
  "segments": [
    {"speaker": "Alex", "voice": "nova", "text": "..."},
    {"speaker": "Jordan", "voice": "onyx", "text": "..."}
  ]
}"""


def _extract_podcast_json(raw: str) -> dict:
    """
    Robustly extract the podcast JSON from a model response.

    Handles:
    - Clean JSON responses (ideal case)
    - Reasoning model output with <think>...</think> blocks
    - JSON embedded in prose / markdown code fences
    - Partial / malformed JSON with a ``segments`` array
    """
    if not raw:
        return {"segments": []}

    # 1. Strip reasoning blocks produced by chain-of-thought models
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # 2. Strip markdown code fences  ```json ... ``` or ``` ... ```
    text = re.sub(r"```(?:json)?\s*([\s\S]*?)\s*```", r"\1", text).strip()

    # 3. Try parsing the cleaned text directly
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 4. Find the first outermost {...} block in the text
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        for i, ch in enumerate(text[brace_start:], start=brace_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[brace_start: i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # 5. Last resort — try to reconstruct a segments array from the raw text
    segs_match = re.search(r'"segments"\s*:\s*(\[.*?\])', raw, re.DOTALL)
    if segs_match:
        try:
            return {"segments": json.loads(segs_match.group(1))}
        except json.JSONDecodeError:
            pass

    logger.error("podcast_json_parse_failed raw_preview=%s", raw[:300])
    return {"segments": []}


def generate_podcast_script(
    summary_text: str, title: str, author: Optional[str] = None
) -> dict:
    """
    Use OpenRouter (``OPENROUTER_PODCAST_MODEL``) to generate a two-host podcast script.
    Returns a dict with a 'segments' list matching PodcastScriptResponse schema.
    """
    settings = get_settings()
    client = get_openrouter_openai_client()
    author_line = f" by {author}" if author else ""
    user_prompt = (
        f'Book: "{title}"{author_line}\n\n'
        f"Summary:\n{summary_text[:7000]}"
    )

    messages = [
        {"role": "system", "content": _PODCAST_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    model = settings.openrouter_podcast_model
    try:
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=messages,
            temperature=0.8,
        )
    except Exception as first_exc:
        logger.warning(
            "podcast_script_json_mode_failed model=%s err=%s — retrying without json_object",
            model,
            first_exc,
        )
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.8,
        )

    raw = response.choices[0].message.content or "{}"
    data = _extract_podcast_json(raw)

    # Normalise: ensure voice matches speaker defaults if missing
    for seg in data.get("segments", []):
        if seg.get("speaker") == "Alex" and not seg.get("voice"):
            seg["voice"] = "nova"
        elif seg.get("speaker") == "Jordan" and not seg.get("voice"):
            seg["voice"] = "onyx"

    return data
