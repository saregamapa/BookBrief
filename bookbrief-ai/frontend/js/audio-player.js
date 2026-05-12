/**
 * BookBrief AI Audio Player
 * ─────────────────────────
 * Provides two playback modes:
 *   • Audiobook — straight TTS narration, section-by-section
 *   • Podcast   — AI-generated two-host discussion (Alex & Jordan)
 *
 * Public API:
 *   BBAudioPlayer.init(summaryId, title, markdown, onClose?)
 *   BBAudioPlayer.destroy()
 */

"use strict";

(function (global) {
  // ═══════════════════════════════════════════════════════════════════════════
  // Constants
  // ═══════════════════════════════════════════════════════════════════════════
  const API_BASE = "/api/v1/audio";
  const LS_KEY_PREFIX = "bb_audio_";

  const VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"];
  const VOICE_LABELS = {
    alloy: "Alloy", echo: "Echo", fable: "Fable",
    onyx: "Onyx", nova: "Nova", shimmer: "Shimmer",
  };
  const SPEEDS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0];
  const AMBIENCE_TYPES = ["off", "library", "rain", "fireplace"];
  const AMBIENCE_LABELS = { off: "None", library: "📚 Library", rain: "🌧 Rain", fireplace: "🔥 Fireplace" };

  // ═══════════════════════════════════════════════════════════════════════════
  // AmbienceEngine — Web Audio API procedural background sounds
  // ═══════════════════════════════════════════════════════════════════════════
  class AmbienceEngine {
    constructor() {
      this._ctx = null;
      this._gainNode = null;
      this._sourceNode = null;
      this._filterNode = null;
      this._active = false;
    }

    _ensureCtx() {
      if (!this._ctx) {
        this._ctx = new (window.AudioContext || window.webkitAudioContext)();
        this._gainNode = this._ctx.createGain();
        this._gainNode.gain.value = 0.06; // quiet by default
        this._gainNode.connect(this._ctx.destination);
      }
    }

    /** Create a noise buffer (white / brown blend). */
    _createNoiseBuffer() {
      const sampleRate = this._ctx.sampleRate;
      const duration = 4; // seconds — will loop
      const frameCount = sampleRate * duration;
      const buffer = this._ctx.createBuffer(1, frameCount, sampleRate);
      const data = buffer.getChannelData(0);
      let last = 0;
      for (let i = 0; i < frameCount; i++) {
        const white = Math.random() * 2 - 1;
        // Brown-ish noise: low-pass blend
        last = (last + 0.02 * white) / 1.02;
        data[i] = last * 3.5; // scale up after LP
      }
      return buffer;
    }

    /** Start ambience. type = "library" | "rain" | "fireplace" */
    start(type) {
      this.stop();
      if (type === "off" || !type) return;
      this._ensureCtx();
      if (this._ctx.state === "suspended") this._ctx.resume();

      const buffer = this._createNoiseBuffer();
      const source = this._ctx.createBufferSource();
      source.buffer = buffer;
      source.loop = true;

      const filter = this._ctx.createBiquadFilter();

      switch (type) {
        case "library":
          // Very soft, muffled rumble — air conditioner / turning pages
          filter.type = "lowpass";
          filter.frequency.value = 400;
          this._gainNode.gain.value = 0.04;
          break;
        case "rain":
          // Broadband with a mid-range presence
          filter.type = "bandpass";
          filter.frequency.value = 1200;
          filter.Q.value = 0.3;
          this._gainNode.gain.value = 0.10;
          break;
        case "fireplace":
          // Warm, gentle crackling feel — low-mid band
          filter.type = "peaking";
          filter.frequency.value = 600;
          filter.gain.value = 8;
          this._gainNode.gain.value = 0.05;
          break;
        default:
          filter.type = "allpass";
      }

      source.connect(filter);
      filter.connect(this._gainNode);
      source.start(0);

      this._sourceNode = source;
      this._filterNode = filter;
      this._active = true;
    }

    stop() {
      if (this._sourceNode) {
        try { this._sourceNode.stop(); } catch (_) {}
        this._sourceNode.disconnect();
        this._sourceNode = null;
      }
      if (this._filterNode) {
        this._filterNode.disconnect();
        this._filterNode = null;
      }
      this._active = false;
    }

    setVolume(v) {
      if (this._gainNode) this._gainNode.gain.value = Math.max(0, Math.min(1, v));
    }

    destroy() {
      this.stop();
      if (this._ctx) {
        this._ctx.close();
        this._ctx = null;
      }
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Markdown section parser
  // ═══════════════════════════════════════════════════════════════════════════

  function parseSections(markdown) {
    if (!markdown || !markdown.trim()) return [{ title: "Summary", text: markdown || "" }];

    // Split on H2 headings
    const parts = markdown.split(/\n(?=## )/);
    const sections = [];

    for (const part of parts) {
      const lines = part.trim().split("\n");
      let title = "Section";
      let text = part.trim();

      const firstLine = lines[0].trim();
      if (firstLine.startsWith("#")) {
        title = firstLine.replace(/^#+\s*/, "").trim();
        text = lines.slice(1).join("\n").trim();
      }

      if (text.length > 20) {
        // Keep each TTS request well below provider limits to avoid chunk-merging artifacts.
        if (text.length > 3000) {
          const subParts = splitAtWordBoundary(text, 2800);
          subParts.forEach((sp, i) => {
            sections.push({ title: i === 0 ? title : `${title} (cont.)`, text: sp });
          });
        } else {
          sections.push({ title, text });
        }
      }
    }

    return sections.length ? sections : [{ title: "Summary", text: markdown }];
  }

  function splitAtWordBoundary(text, maxLen) {
    const chunks = [];
    let remaining = text;
    while (remaining.length > maxLen) {
      let idx = remaining.lastIndexOf(" ", maxLen);
      if (idx < maxLen * 0.7) idx = maxLen; // fallback hard split
      chunks.push(remaining.slice(0, idx).trim());
      remaining = remaining.slice(idx).trim();
    }
    if (remaining) chunks.push(remaining);
    return chunks;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Injected CSS
  // ═══════════════════════════════════════════════════════════════════════════
  const PLAYER_CSS = `
/* ── BookBrief Audio Player ─────────────────────────────────────────────── */
#bb-audio-player {
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 9999;
  background: #1a1a2e; color: #e8e8f0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px; box-shadow: 0 -4px 24px rgba(0,0,0,0.4);
  transition: transform 0.3s ease; user-select: none;
}
#bb-audio-player.bb-ap-minimised { transform: translateY(calc(100% - 48px)); }
#bb-audio-player * { box-sizing: border-box; }

/* Top bar */
.bb-ap-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; border-bottom: 1px solid rgba(255,255,255,0.08);
  cursor: pointer;
}
.bb-ap-bar-left { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; }
.bb-ap-icon { font-size: 18px; flex-shrink: 0; }
.bb-ap-meta { min-width: 0; }
.bb-ap-title { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 300px; font-size: 13px; }
.bb-ap-section-name { font-size: 11px; color: #9090b0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 260px; }
.bb-ap-badge { font-size: 10px; font-weight: 700; letter-spacing: 0.08em; padding: 2px 7px; border-radius: 10px; background: #6c63ff; color: #fff; flex-shrink: 0; }
.bb-ap-badge.podcast { background: #e0456e; }
.bb-ap-bar-right { display: flex; align-items: center; gap: 6px; }
.bb-ap-min-btn { background: none; border: none; color: #9090b0; cursor: pointer; font-size: 18px; padding: 2px 4px; line-height: 1; }
.bb-ap-min-btn:hover { color: #fff; }
.bb-ap-close-btn { background: none; border: none; color: #9090b0; cursor: pointer; font-size: 18px; padding: 2px 4px; line-height: 1; }
.bb-ap-close-btn:hover { color: #e74c3c; }

/* Main body */
.bb-ap-body { padding: 12px 16px; }

/* Progress */
.bb-ap-progress-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.bb-ap-time { font-size: 11px; color: #9090b0; width: 38px; text-align: center; flex-shrink: 0; }
.bb-ap-progress { flex: 1; -webkit-appearance: none; appearance: none; height: 4px; border-radius: 2px;
  background: rgba(255,255,255,0.12); cursor: pointer; outline: none; }
.bb-ap-progress::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: #6c63ff; cursor: pointer; }
.bb-ap-progress::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%; background: #6c63ff; border: none; cursor: pointer; }

/* Controls */
.bb-ap-controls { display: flex; align-items: center; justify-content: center; gap: 4px; margin-bottom: 12px; }
.bb-ap-btn { background: none; border: none; color: #c8c8e0; cursor: pointer; padding: 6px 10px; border-radius: 8px; font-size: 20px; transition: background 0.15s, color 0.15s; }
.bb-ap-btn:hover { background: rgba(255,255,255,0.08); color: #fff; }
.bb-ap-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.bb-ap-btn.play-pause { font-size: 26px; background: #6c63ff; color: #fff; border-radius: 50%; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; padding: 0; }
.bb-ap-btn.play-pause:hover { background: #7c72ff; }
.bb-ap-btn.play-pause:disabled { background: #444; }
.bb-ap-loading-dot { display: inline-block; width: 8px; height: 8px; border: 2px solid #fff; border-top-color: transparent; border-radius: 50%; animation: bb-spin 0.8s linear infinite; }
@keyframes bb-spin { to { transform: rotate(360deg); } }

/* Options row */
.bb-ap-options { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.bb-ap-select { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); color: #e8e8f0; padding: 4px 8px; border-radius: 6px; font-size: 12px; cursor: pointer; outline: none; }
.bb-ap-select:hover { background: rgba(255,255,255,0.12); }
.bb-ap-select option { background: #1a1a2e; }
.bb-ap-label { font-size: 11px; color: #7070a0; white-space: nowrap; }
.bb-ap-chapter-sel { flex: 1; max-width: 240px; }

/* Mode tabs */
.bb-ap-modes { display: flex; gap: 4px; }
.bb-ap-mode-btn { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); color: #9090b0; padding: 3px 10px; border-radius: 6px; font-size: 11px; cursor: pointer; transition: all 0.15s; }
.bb-ap-mode-btn.active { background: #6c63ff; border-color: #6c63ff; color: #fff; }
.bb-ap-mode-btn.podcast.active { background: #e0456e; border-color: #e0456e; }

/* Loading overlay */
.bb-ap-generating {
  display: none; align-items: center; justify-content: center; gap: 8px;
  padding: 8px 0 4px; font-size: 12px; color: #9090b0;
}
.bb-ap-generating.visible { display: flex; }

/* Transcript / podcast script panel */
.bb-ap-transcript {
  display: none; max-height: 120px; overflow-y: auto; margin-top: 8px;
  background: rgba(0,0,0,0.2); border-radius: 8px; padding: 8px 12px;
  font-size: 12px; line-height: 1.5; color: #b0b0d0;
}
.bb-ap-transcript.visible { display: block; }
.bb-ap-transcript .speaker { font-weight: 700; color: #c8c8ff; margin-right: 4px; }
.bb-ap-transcript .speaker.jordan { color: #ffb86c; }
.bb-ap-transcript .seg { padding: 3px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
.bb-ap-transcript .seg:last-child { border-bottom: none; }
.bb-ap-transcript .seg.active { background: rgba(108,99,255,0.15); border-radius: 4px; padding: 3px 6px; margin: 0 -6px; }
`;

  // ═══════════════════════════════════════════════════════════════════════════
  // Player HTML template
  // ═══════════════════════════════════════════════════════════════════════════
  function buildPlayerHTML(title) {
    return `
<div class="bb-ap-bar" id="bb-ap-bar">
  <div class="bb-ap-bar-left">
    <span class="bb-ap-icon">🎧</span>
    <div class="bb-ap-meta">
      <div class="bb-ap-title" id="bb-ap-title">${_esc(title)}</div>
      <div class="bb-ap-section-name" id="bb-ap-section-name">Loading…</div>
    </div>
  </div>
  <div class="bb-ap-bar-right">
    <span class="bb-ap-badge" id="bb-ap-badge">AUDIOBOOK</span>
    <button class="bb-ap-min-btn" id="bb-ap-min-btn" title="Minimise">⌄</button>
    <button class="bb-ap-close-btn" id="bb-ap-close-btn" title="Close player">✕</button>
  </div>
</div>
<div class="bb-ap-body" id="bb-ap-body">
  <!-- Progress -->
  <div class="bb-ap-progress-row">
    <span class="bb-ap-time" id="bb-ap-time-cur">0:00</span>
    <input type="range" class="bb-ap-progress" id="bb-ap-progress" min="0" max="100" value="0" step="0.1">
    <span class="bb-ap-time" id="bb-ap-time-dur">0:00</span>
  </div>
  <!-- Controls -->
  <div class="bb-ap-controls">
    <button class="bb-ap-btn" id="bb-ap-prev" title="Previous section">⏮</button>
    <button class="bb-ap-btn" id="bb-ap-rew" title="Rewind 10s">⏪</button>
    <button class="bb-ap-btn play-pause" id="bb-ap-play" title="Play / Pause">▶</button>
    <button class="bb-ap-btn" id="bb-ap-fwd" title="Forward 10s">⏩</button>
    <button class="bb-ap-btn" id="bb-ap-next" title="Next section">⏭</button>
  </div>
  <!-- Options -->
  <div class="bb-ap-options">
    <div class="bb-ap-modes">
      <button class="bb-ap-mode-btn active" id="bb-ap-mode-audio" data-mode="audiobook">📖 Audiobook</button>
      <button class="bb-ap-mode-btn podcast" id="bb-ap-mode-podcast" data-mode="podcast">🎙 Podcast</button>
    </div>

    <select class="bb-ap-select bb-ap-chapter-sel" id="bb-ap-chapter-sel" title="Jump to chapter/segment"></select>

    <span class="bb-ap-label">Voice:</span>
    <select class="bb-ap-select" id="bb-ap-voice-sel" title="Narrator voice"></select>

    <span class="bb-ap-label">Speed:</span>
    <select class="bb-ap-select" id="bb-ap-speed-sel" title="Playback speed"></select>

    <span class="bb-ap-label">Ambience:</span>
    <select class="bb-ap-select" id="bb-ap-ambience-sel" title="Background sounds"></select>
  </div>

  <!-- Generating indicator -->
  <div class="bb-ap-generating" id="bb-ap-generating">
    <span class="bb-ap-loading-dot"></span>
    <span id="bb-ap-gen-msg">Generating audio…</span>
  </div>

  <!-- Podcast transcript -->
  <div class="bb-ap-transcript" id="bb-ap-transcript"></div>
</div>`;
  }

  function _esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function fmt(secs) {
    if (!isFinite(secs) || secs < 0) return "0:00";
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // AudioPlayer — core engine
  // ═══════════════════════════════════════════════════════════════════════════
  class AudioPlayer {
    constructor(summaryId, title, markdown, onClose, options) {
      this._id = summaryId;
      this._title = title;
      this._markdown = markdown;
      this._onClose = onClose || null;

      // State
      this._mode = (options && options.startMode === "podcast") ? "podcast" : "audiobook"; // "audiobook" | "podcast"
      this._sections = parseSections(markdown); // audiobook sections
      this._podcastSegments = null; // array of PodcastSegment objects
      this._currentIndex = 0;
      this._voice = "onyx";
      this._speed = 1.0;
      this._ambience = "off";
      this._minimised = false;

      // Audio
      this._audio = new Audio();
      this._audio.preload = "auto";
      this._audioCache = new Map(); // key -> blob URL
      this._prefetchTimer = null;
      this._fetchingIndex = new Set();
      this._retryCount = 0;
      this._maxRetries = 2;

      // Ambience
      this._ambienceEngine = new AmbienceEngine();

      // DOM refs (set after mount)
      this._el = null;
      this._els = {};

      this._loadState();
    }

    // ── State persistence ────────────────────────────────────────────────────

    _lsKey() { return LS_KEY_PREFIX + this._id; }

    _loadState() {
      try {
        const raw = localStorage.getItem(this._lsKey());
        if (!raw) return;
        const s = JSON.parse(raw);
        if (s.mode) this._mode = s.mode;
        if (s.voice && VOICES.includes(s.voice)) this._voice = s.voice;
        if (s.speed && SPEEDS.includes(s.speed)) this._speed = s.speed;
        if (s.ambience && AMBIENCE_TYPES.includes(s.ambience)) this._ambience = s.ambience;
        if (typeof s.index === "number") this._currentIndex = s.index;
      } catch (_) {}
    }

    _saveState() {
      try {
        localStorage.setItem(this._lsKey(), JSON.stringify({
          mode: this._mode, voice: this._voice, speed: this._speed,
          ambience: this._ambience, index: this._currentIndex,
        }));
      } catch (_) {}
    }

    // ── Mount ────────────────────────────────────────────────────────────────

    mount() {
      // Inject CSS once
      if (!document.getElementById("bb-audio-player-css")) {
        const style = document.createElement("style");
        style.id = "bb-audio-player-css";
        style.textContent = PLAYER_CSS;
        document.head.appendChild(style);
      }

      // Create container
      const el = document.createElement("div");
      el.id = "bb-audio-player";
      el.innerHTML = buildPlayerHTML(this._title);
      document.body.appendChild(el);
      this._el = el;

      // Cache frequently accessed elements
      const $ = (id) => document.getElementById(id);
      this._els = {
        bar: $("bb-ap-bar"), badge: $("bb-ap-badge"),
        sectionName: $("bb-ap-section-name"),
        timeCur: $("bb-ap-time-cur"), timeDur: $("bb-ap-time-dur"),
        progress: $("bb-ap-progress"),
        play: $("bb-ap-play"), prev: $("bb-ap-prev"), next: $("bb-ap-next"),
        rew: $("bb-ap-rew"), fwd: $("bb-ap-fwd"),
        modeAudio: $("bb-ap-mode-audio"), modePodcast: $("bb-ap-mode-podcast"),
        chapterSel: $("bb-ap-chapter-sel"),
        voiceSel: $("bb-ap-voice-sel"), speedSel: $("bb-ap-speed-sel"),
        ambienceSel: $("bb-ap-ambience-sel"),
        generating: $("bb-ap-generating"), genMsg: $("bb-ap-gen-msg"),
        transcript: $("bb-ap-transcript"),
        minBtn: $("bb-ap-min-btn"), closeBtn: $("bb-ap-close-btn"),
      };

      this._populateSelects();
      this._bindEvents();
      this._applyMode();

      // Validate index
      const maxIdx = this._currentItems().length - 1;
      if (this._currentIndex > maxIdx) this._currentIndex = 0;

      this._updateChapterSelect();
      this._syncUI();
      if (this._mode === "podcast") {
        this._generatePodcast();
      } else {
        this._startPlayback();
      }
    }

    _populateSelects() {
      const { voiceSel, speedSel, ambienceSel } = this._els;

      VOICES.forEach((v) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = VOICE_LABELS[v];
        if (v === this._voice) o.selected = true;
        voiceSel.appendChild(o);
      });

      SPEEDS.forEach((s) => {
        const o = document.createElement("option");
        o.value = s; o.textContent = s + "×";
        if (s === this._speed) o.selected = true;
        speedSel.appendChild(o);
      });

      AMBIENCE_TYPES.forEach((a) => {
        const o = document.createElement("option");
        o.value = a; o.textContent = AMBIENCE_LABELS[a];
        if (a === this._ambience) o.selected = true;
        ambienceSel.appendChild(o);
      });
    }

    // ── Events ───────────────────────────────────────────────────────────────

    _bindEvents() {
      const { bar, play, prev, next, rew, fwd, progress,
              modeAudio, modePodcast, chapterSel, voiceSel, speedSel,
              ambienceSel, minBtn, closeBtn } = this._els;
      const a = this._audio;

      // Bar click → toggle minimise (but not on buttons)
      bar.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        this._toggleMinimise();
      });

      // Play/Pause
      play.addEventListener("click", () => {
        if (a.paused) this._resume(); else this._pause();
      });

      // Prev / Next
      prev.addEventListener("click", () => this._prevSection());
      next.addEventListener("click", () => this._nextSection());

      // Rewind / Forward
      rew.addEventListener("click", () => { a.currentTime = Math.max(0, a.currentTime - 10); });
      fwd.addEventListener("click", () => { a.currentTime = Math.min(a.duration || 0, a.currentTime + 10); });

      // Progress seek
      progress.addEventListener("input", () => {
        if (a.duration) a.currentTime = (progress.value / 100) * a.duration;
      });

      // Audio events
      a.addEventListener("timeupdate", () => this._onTimeUpdate());
      a.addEventListener("ended", () => this._onEnded());
      a.addEventListener("play", () => this._onPlay());
      a.addEventListener("pause", () => this._onPause());
      a.addEventListener("error", () => this._onAudioError());

      // Mode buttons
      modeAudio.addEventListener("click", () => this._switchMode("audiobook"));
      modePodcast.addEventListener("click", () => this._switchMode("podcast"));

      // Chapter select
      chapterSel.addEventListener("change", () => {
        const idx = parseInt(chapterSel.value, 10);
        if (!isNaN(idx)) this._jumpTo(idx);
      });

      // Voice
      voiceSel.addEventListener("change", () => {
        this._voice = voiceSel.value;
        // Bust cache for audiobook (voice changed) — keep podcast (has own voices)
        if (this._mode === "audiobook") this._audioCache.clear();
        this._saveState();
        this._startPlayback();
      });

      // Speed
      speedSel.addEventListener("change", () => {
        this._speed = parseFloat(speedSel.value);
        a.playbackRate = this._speed;
        this._saveState();
      });

      // Ambience
      ambienceSel.addEventListener("change", () => {
        this._ambience = ambienceSel.value;
        this._saveState();
        if (this._ambience === "off") {
          this._ambienceEngine.stop();
        } else {
          this._ambienceEngine.start(this._ambience);
        }
      });

      // Minimise
      minBtn.addEventListener("click", (e) => { e.stopPropagation(); this._toggleMinimise(); });

      // Close
      closeBtn.addEventListener("click", (e) => { e.stopPropagation(); this.destroy(); });
    }

    // ── Mode ─────────────────────────────────────────────────────────────────

    _applyMode() {
      const { modeAudio, modePodcast, badge, voiceSel } = this._els;
      const isPodcast = this._mode === "podcast";

      modeAudio.classList.toggle("active", !isPodcast);
      modePodcast.classList.toggle("active", isPodcast);
      badge.textContent = isPodcast ? "PODCAST" : "AUDIOBOOK";
      badge.classList.toggle("podcast", isPodcast);

      // Voice select only meaningful in audiobook mode
      voiceSel.disabled = isPodcast;
      voiceSel.style.opacity = isPodcast ? "0.4" : "1";
    }

    _switchMode(mode) {
      if (this._mode === mode) return;
      this._pause();
      this._mode = mode;
      this._currentIndex = 0;
      this._retryCount = 0;
      this._saveState();
      this._applyMode();

      if (mode === "podcast" && !this._podcastSegments) {
        this._generatePodcast();
      } else {
        this._updateChapterSelect();
        this._syncUI();
        this._startPlayback();
      }
    }

    _currentItems() {
      if (this._mode === "podcast" && this._podcastSegments) {
        return this._podcastSegments;
      }
      return this._sections;
    }

    _currentItem() {
      return this._currentItems()[this._currentIndex] || null;
    }

    // ── Podcast generation ───────────────────────────────────────────────────

    async _generatePodcast() {
      this._showGenerating("Generating podcast script with AI…");
      this._disableControls(true);

      try {
        const token = this._getToken();
        const headers = { "Content-Type": "application/json" };
        if (token) headers["Authorization"] = "Bearer " + token;

        const summaryText = this._sections.map((s) => `## ${s.title}\n${s.text}`).join("\n\n");
        const res = await fetch(`${API_BASE}/podcast-script`, {
          method: "POST",
          headers,
          body: JSON.stringify({ summary_text: summaryText, title: this._title }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        this._podcastSegments = data.segments || [];
      } catch (err) {
        console.error("[BBPlayer] Podcast generation failed:", err);
        this._hideGenerating();
        this._disableControls(false);
        alert("Podcast generation failed. Please try again.");
        // Revert to audiobook
        this._mode = "audiobook";
        this._applyMode();
        this._updateChapterSelect();
        this._syncUI();
        return;
      }

      // Script is ready — now pre-generate ALL audio segments before playing
      this._updateChapterSelect();
      this._renderTranscript();
      this._syncUI();
      await this._generateAllPodcastAudio();
    }

    /**
     * Pre-generates audio for every podcast segment sequentially, showing
     * live progress. Sequential (not parallel) to avoid TTS API rate limits.
     * Only starts playback once ALL segments are attempted so the podcast
     * plays through like a real continuous recording.
     */
    async _generateAllPodcastAudio() {
      const segments = this._podcastSegments;
      if (!segments || !segments.length) return;

      const total = segments.length;
      let completed = 0;
      let firstError = null;
      const failedIndices = new Set();

      const updateProgress = () => {
        if (this._els.genMsg) {
          this._els.genMsg.textContent =
            `Generating podcast audio… ${completed} / ${total} segments ready`;
        }
      };

      this._showGenerating(`Generating podcast audio… 0 / ${total} segments ready`);
      this._disableControls(true);

      // Sequential generation — avoids overwhelming the TTS API with parallel requests
      for (let index = 0; index < segments.length; index++) {
        try {
          await this._fetchAudio(index);
        } catch (err) {
          console.error(`[BBPlayer] Audio generation failed for segment ${index}:`, err);
          if (!firstError) firstError = err;
          failedIndices.add(index);
        }
        completed++;
        updateProgress();
      }

      this._hideGenerating();
      this._disableControls(false);

      const successCount = total - failedIndices.size;

      // If nothing at all was generated, show the real error and bail out
      if (successCount === 0) {
        const detail = firstError
          ? firstError.message.replace(/^Audio generation failed[:\s]*/i, "").trim()
          : "TTS provider returned an error";
        this._els.sectionName.textContent =
          `⚠ ${detail.slice(0, 80) || "Audio generation failed — check API key / quota"}`;
        // Revert to audiobook so user isn't stuck
        this._mode = "audiobook";
        this._applyMode();
        this._updateChapterSelect();
        this._syncUI();
        return;
      }

      // Warn if partial failures occurred but at least some audio is ready
      if (failedIndices.size > 0) {
        console.warn(
          `[BBPlayer] ${failedIndices.size}/${total} segments failed. ` +
          `Playing the ${successCount} available segments.`
        );
      }

      // Advance to first successfully generated segment if index 0 failed
      if (failedIndices.has(this._currentIndex)) {
        let firstGood = 0;
        while (firstGood < total && failedIndices.has(firstGood)) firstGood++;
        if (firstGood < total) this._currentIndex = firstGood;
      }

      this._startPlayback();
    }

    // ── Playback ─────────────────────────────────────────────────────────────

    async _startPlayback() {
      const item = this._currentItem();
      if (!item) return;

      this._syncUI();

      const cacheKey = this._cacheKey(this._currentIndex);
      let blobUrl = this._audioCache.get(cacheKey);

      if (!blobUrl) {
        this._showGenerating("Generating audio…");
        try {
          blobUrl = await this._fetchAudio(this._currentIndex);
        } catch (err) {
          console.error("[BBPlayer] Audio fetch failed:", err);
          this._hideGenerating();
          // Show the real backend error, not just a generic message
          const detail = (err.message || "")
            .replace(/^Audio generation failed[:\s]*/i, "")
            .replace(/^HTTP \d+[:\s]*/i, "")
            .trim();
          this._els.sectionName.textContent = detail
            ? `⚠ ${detail.slice(0, 80)}`
            : "⚠ Audio failed — check your API key or quota";
          return;
        }
        this._hideGenerating();
      }

      this._audio.src = blobUrl;
      this._retryCount = 0;
      this._audio.playbackRate = this._speed;
      this._audio.play().catch((e) => console.warn("[BBPlayer] play() blocked:", e));

      // Prefetch next
      this._schedulePrefetch();
    }

    _cacheKey(index) {
      if (this._mode === "podcast" && this._podcastSegments) {
        const seg = this._podcastSegments[index];
        return `podcast:${this._id}:${index}:${seg ? seg.voice : ""}`;
      }
      return `audio:${this._id}:${index}:${this._voice}`;
    }

    async _fetchAudio(index) {
      if (this._fetchingIndex.has(index)) {
        // Another call is already fetching this index — wait for it to populate the cache.
        // Manus TTS can take up to 8 minutes, so give it 12 minutes before giving up.
        return new Promise((resolve, reject) => {
          const check = setInterval(() => {
            const url = this._audioCache.get(this._cacheKey(index));
            if (url) { clearInterval(check); resolve(url); }
          }, 300);
          setTimeout(() => {
            clearInterval(check);
            reject(new Error("Timed out waiting for in-flight audio fetch"));
          }, 720_000);
        });
      }

      this._fetchingIndex.add(index);
      try {
        const item = this._currentItems()[index];
        if (!item) throw new Error("No item at index " + index);

        const text = item.text;
        const voice = this._mode === "podcast" ? item.voice : this._voice;

        const token = this._getToken();
        const authHeaders = {};
        if (token) authHeaders["Authorization"] = "Bearer " + token;

        // ── Step 1: Submit the TTS job (returns immediately with job_id) ───────
        const submitRes = await fetch(`${API_BASE}/narrate`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify({ text, voice }),
        });
        if (!submitRes.ok) {
          let detail = "";
          try { detail = (await submitRes.json()).detail || ""; } catch (_) {}
          throw new Error(`HTTP ${submitRes.status} submitting TTS job${detail ? ": " + detail : ""}`);
        }
        const { job_id } = await submitRes.json();
        if (!job_id) throw new Error("Server returned no job_id");

        // ── Step 2: Poll until audio is ready ────────────────────────────────
        //   202 → still generating (keep polling)
        //   200 → binary audio ready
        //   4xx/5xx → error
        const MAX_POLL_MS  = 600_000; // 10 minutes (Manus can be slow)
        const POLL_INTERVAL =   3_000; // 3 seconds between polls
        const startTime = Date.now();

        while (Date.now() - startTime < MAX_POLL_MS) {
          await new Promise((r) => setTimeout(r, POLL_INTERVAL));

          // Show elapsed time to the user (only for the segment currently playing)
          if (this._currentIndex === index && this._els.genMsg) {
            const elapsed = Math.round((Date.now() - startTime) / 1000);
            this._els.genMsg.textContent = `Generating audio… ${elapsed}s`;
          }

          const pollRes = await fetch(`${API_BASE}/narrate/poll/${job_id}`, {
            headers: authHeaders,
          });

          if (pollRes.status === 202) {
            // Still in progress — continue polling
            continue;
          }

          if (!pollRes.ok) {
            let detail = "";
            try { detail = (await pollRes.json()).detail || ""; } catch (_) {}
            throw new Error(
              `Audio generation failed (HTTP ${pollRes.status})${detail ? ": " + detail : ""}`
            );
          }

          // HTTP 200 — audio bytes are in the body
          const blob = await pollRes.blob();
          const okSize = blob && blob.size >= 256;
          const ct = (blob && blob.type) || "";
          const okType =
            !ct ||
            ct.startsWith("audio/") ||
            ct === "application/octet-stream" ||
            ct === "binary/octet-stream";
          if (!okSize || !okType) {
            let detail = "";
            try {
              detail = blob ? await blob.text() : "";
            } catch (_) {}
            throw new Error(detail || "Server returned an invalid audio payload");
          }

          const url = URL.createObjectURL(blob);
          this._audioCache.set(this._cacheKey(index), url);
          return url;
        }

        throw new Error(`Audio generation timed out after ${MAX_POLL_MS / 1000}s`);
      } finally {
        this._fetchingIndex.delete(index);
      }
    }

    _schedulePrefetch() {
      clearTimeout(this._prefetchTimer);
      this._prefetchTimer = setTimeout(() => {
        const next = this._currentIndex + 1;
        const items = this._currentItems();
        if (next < items.length && !this._audioCache.has(this._cacheKey(next))) {
          this._fetchAudio(next).catch(() => {}); // fire-and-forget
        }
      }, 1500);
    }

    _resume() {
      if (!this._audio.src || this._audio.src === window.location.href) {
        this._startPlayback();
        return;
      }
      this._audio.playbackRate = this._speed;
      this._audio.play().catch(() => {});
      if (this._ambience !== "off") this._ambienceEngine.start(this._ambience);
    }

    _pause() {
      this._audio.pause();
      this._ambienceEngine.stop();
    }

    _prevSection() {
      if (this._currentIndex > 0) {
        this._currentIndex--;
        this._saveState();
        this._syncUI();
        this._startPlayback();
      }
    }

    _nextSection() {
      const items = this._currentItems();
      if (this._currentIndex < items.length - 1) {
        this._currentIndex++;
        this._saveState();
        this._syncUI();
        this._startPlayback();
      }
    }

    _jumpTo(index) {
      this._currentIndex = index;
      this._saveState();
      this._syncUI();
      this._startPlayback();
    }

    // ── Audio events ─────────────────────────────────────────────────────────

    _onTimeUpdate() {
      const a = this._audio;
      if (!isFinite(a.duration)) return;
      const pct = (a.currentTime / a.duration) * 100;
      this._els.progress.value = pct;
      this._els.timeCur.textContent = fmt(a.currentTime);
      this._els.timeDur.textContent = fmt(a.duration);
    }

    _onEnded() {
      const items = this._currentItems();
      if (this._currentIndex < items.length - 1) {
        // Advance to next segment that has cached audio (skip any that failed to generate)
        let next = this._currentIndex + 1;
        while (next < items.length && !this._audioCache.has(this._cacheKey(next))) {
          next++;
        }
        if (next < items.length) {
          this._currentIndex = next;
          this._saveState();
          this._syncUI();
          this._startPlayback();
        } else {
          this._els.play.textContent = "▶";
          this._els.sectionName.textContent = "Finished";
        }
      } else {
        this._els.play.textContent = "▶";
        this._els.sectionName.textContent = "Finished";
      }
    }

    _onPlay() {
      this._els.play.textContent = "⏸";
      if (this._ambience !== "off") this._ambienceEngine.start(this._ambience);
      if (this._minimised) this._el.classList.add("bb-ap-minimised");
    }

    _onPause() {
      this._els.play.textContent = "▶";
    }

    _onAudioError() {
      console.error("[BBPlayer] Audio error", this._audio.error);
      // Remove bad cache entry so next attempt re-fetches
      this._audioCache.delete(this._cacheKey(this._currentIndex));
      this._hideGenerating();
      if (this._retryCount < this._maxRetries) {
        this._retryCount += 1;
        this._els.sectionName.textContent = `⚠ Playback error — retrying (${this._retryCount}/${this._maxRetries})…`;
        setTimeout(() => this._startPlayback(), 1500);
        return;
      }
      this._els.sectionName.textContent = "⚠ Audio failed. Try a different voice or retry later.";
    }

    // ── UI sync ──────────────────────────────────────────────────────────────

    _syncUI() {
      const item = this._currentItem();
      const items = this._currentItems();
      const { sectionName, prev, next, chapterSel, transcript } = this._els;

      sectionName.textContent = item
        ? (this._mode === "podcast"
            ? `🎙 ${item.speaker} · ${this._currentIndex + 1} / ${items.length}`
            : `${item.title} (${this._currentIndex + 1}/${items.length})`)
        : "—";

      prev.disabled = this._currentIndex === 0;
      next.disabled = this._currentIndex >= items.length - 1;

      // Sync chapter select
      chapterSel.value = String(this._currentIndex);

      // Highlight active transcript line
      if (this._mode === "podcast" && transcript.classList.contains("visible")) {
        transcript.querySelectorAll(".seg").forEach((el, i) => {
          el.classList.toggle("active", i === this._currentIndex);
        });
        const activeEl = transcript.querySelector(".seg.active");
        if (activeEl) activeEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    }

    _updateChapterSelect() {
      const sel = this._els.chapterSel;
      sel.innerHTML = "";
      const items = this._currentItems();
      items.forEach((item, i) => {
        const o = document.createElement("option");
        o.value = i;
        o.textContent = this._mode === "podcast"
          ? `${i + 1}. ${item.speaker}: ${item.text.slice(0, 40)}…`
          : `${i + 1}. ${item.title}`;
        if (i === this._currentIndex) o.selected = true;
        sel.appendChild(o);
      });
    }

    _renderTranscript() {
      const { transcript } = this._els;
      if (!this._podcastSegments) return;
      transcript.innerHTML = this._podcastSegments
        .map((seg, i) => `<div class="seg${i === this._currentIndex ? " active" : ""}"><span class="speaker${seg.speaker === "Jordan" ? " jordan" : ""}">${_esc(seg.speaker)}:</span>${_esc(seg.text)}</div>`)
        .join("");
      transcript.classList.add("visible");
    }

    _showGenerating(msg) {
      this._els.genMsg.textContent = msg;
      this._els.generating.classList.add("visible");
      this._els.play.disabled = true;
    }

    _hideGenerating() {
      this._els.generating.classList.remove("visible");
      this._els.play.disabled = false;
    }

    _disableControls(disabled) {
      ["prev", "next", "rew", "fwd", "modeAudio", "modePodcast", "chapterSel"].forEach((k) => {
        if (this._els[k]) this._els[k].disabled = disabled;
      });
    }

    _toggleMinimise() {
      this._minimised = !this._minimised;
      this._el.classList.toggle("bb-ap-minimised", this._minimised);
      this._els.minBtn.textContent = this._minimised ? "⌃" : "⌄";
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    _getToken() {
      try {
        if (window.BBAuth && typeof window.BBAuth.getToken === "function") {
          return window.BBAuth.getToken();
        }
        return localStorage.getItem("bb_token") || null;
      } catch (_) { return null; }
    }

    // ── Destroy ──────────────────────────────────────────────────────────────

    destroy() {
      clearTimeout(this._prefetchTimer);
      this._pause();
      this._ambienceEngine.destroy();

      // Revoke blob URLs
      for (const url of this._audioCache.values()) {
        try { URL.revokeObjectURL(url); } catch (_) {}
      }
      this._audioCache.clear();

      this._audio.src = "";
      if (this._el) {
        this._el.remove();
        this._el = null;
      }

      this._saveState();
      if (typeof this._onClose === "function") this._onClose();
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Public API
  // ═══════════════════════════════════════════════════════════════════════════
  let _instance = null;

  const BBAudioPlayer = {
    /**
     * Initialise (or re-init) the audio player.
     * @param {string} summaryId  Unique ID for localStorage state key
     * @param {string} title      Book/summary title
     * @param {string} markdown   Full Markdown text of the summary
     * @param {Function} [onClose] Optional callback when player is closed
     */
    init(summaryId, title, markdown, onClose, options) {
      if (_instance) _instance.destroy();
      _instance = new AudioPlayer(summaryId, title, markdown, onClose, options || {});
      _instance.mount();
      return _instance;
    },

    /** Destroy any active player. */
    destroy() {
      if (_instance) {
        _instance.destroy();
        _instance = null;
      }
    },

    /** Returns true if a player is currently mounted. */
    isActive() {
      return _instance !== null;
    },
  };

  global.BBAudioPlayer = BBAudioPlayer;

})(window);
