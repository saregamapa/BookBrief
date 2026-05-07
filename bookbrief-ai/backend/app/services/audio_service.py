"""
Audio service: OpenAI TTS narration + GPT-powered podcast script generation.
"""
import re
import json
import base64
import logging
from typing import List, Optional

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Lazy client — created once on first use
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


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


def _chunk_text(text: str, max_chars: int = 3200) -> List[str]:
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
    Convert text to speech audio bytes.
    Uses Manus AI tasks when MANUS_API_KEY is set; otherwise OpenAI TTS (MP3).
    Handles long texts by chunking; OpenAI chunks are concatenated as raw MP3.
    Manus chunks are concatenated as raw bytes (typically MP3 per chunk).
    """
    cleaned = _clean_for_tts(text)
    chunks = _chunk_text(cleaned)

    if settings.manus_api_key.strip():
        from app.services import manus_audio

        audio_parts: List[bytes] = []
        for chunk in chunks:
            if not chunk.strip():
                continue
            audio_parts.append(
                manus_audio.synthesize_speech_chunk(
                    chunk,
                    voice,
                    settings.manus_api_key.strip(),
                    timeout_seconds=float(settings.manus_tts_timeout_seconds),
                    agent_profile=settings.manus_agent_profile,
                )
            )
        merged = b"".join(audio_parts)
        if len(merged) == 0:
            raise RuntimeError("No audio generated for provided text")
        return merged

    client = _get_client()
    audio_parts_oai: List[bytes] = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,  # type: ignore[arg-type]
            input=chunk,
        )
        raw = getattr(response, "content", None)
        if not raw and hasattr(response, "read"):
            raw = response.read()

        if isinstance(raw, str):
            try:
                raw = base64.b64decode(raw, validate=False)
            except Exception:
                raw = raw.encode("utf-8")

        if not isinstance(raw, (bytes, bytearray)) or len(raw) == 0:
            raise RuntimeError("TTS provider returned empty audio payload")

        audio_parts_oai.append(bytes(raw))

    merged_oai = b"".join(audio_parts_oai)
    if len(merged_oai) == 0:
        raise RuntimeError("No audio generated for provided text")
    return merged_oai


# ---------------------------------------------------------------------------
# Podcast script generation
# ---------------------------------------------------------------------------

_PODCAST_SYSTEM_PROMPT = """You are a scriptwriter for a book-discussion podcast called "Between the Pages".
The show has two hosts:
  • Alex — enthusiastic, asks probing questions, focuses on themes and meaning (voice: nova)
  • Jordan — analytical, provides deeper context, connects ideas to real life (voice: onyx)

Given a book summary, write an engaging 10–14-segment conversation.
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


def generate_podcast_script(
    summary_text: str, title: str, author: Optional[str] = None
) -> dict:
    """
    Use GPT to generate a two-host podcast discussion script.
    Returns a dict with a 'segments' list matching PodcastScriptResponse schema.
    """
    client = _get_client()
    author_line = f" by {author}" if author else ""
    user_prompt = (
        f'Book: "{title}"{author_line}\n\n'
        f"Summary:\n{summary_text[:7000]}"
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _PODCAST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
    )

    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse podcast JSON: %s", raw[:200])
        data = {"segments": []}

    # Normalise: ensure voice matches speaker defaults if missing
    for seg in data.get("segments", []):
        if seg.get("speaker") == "Alex" and not seg.get("voice"):
            seg["voice"] = "nova"
        elif seg.get("speaker") == "Jordan" and not seg.get("voice"):
            seg["voice"] = "onyx"

    return data
