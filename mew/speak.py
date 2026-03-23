"""
mew.speak — synthesize text to a WAV file via KittenTTS.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

MODEL_REGISTRY = {
    "mini":      "KittenML/kitten-tts-mini-0.8",
    "micro":     "KittenML/kitten-tts-micro-0.8",
    "nano":      "KittenML/kitten-tts-nano-0.8",
    "nano-int8": "KittenML/kitten-tts-nano-0.8-int8",
}

PREFS_FILE = Path.home() / ".config" / "mew" / "prefs.json"
CACHE_DIR  = Path.home() / ".cache"  / "mew" / "models"
LOG_FILE   = Path.home() / ".local" / "share" / "mew" / "synthesis.jsonl"

_MIN_SAMPLES_FOR_ESTIMATE = 3


def _load_prefs() -> dict:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"model": "micro", "voice": "Hugo"}


# ── Phoneme counting ────────────────────────────────────────────────────────

def _count_phonemes(text: str) -> int:
    """Count phonemes using the same espeak backend that kittentts uses."""
    import phonemizer
    backend = phonemizer.backend.EspeakBackend(
        language="en-us", preserve_punctuation=True, with_stress=True,
    )
    # phonemize returns a list of strings (one per input sentence)
    phonemes = backend.phonemize([text])
    # Count non-space phoneme characters (consistent with how kittentts
    # tokenises them via TextCleaner)
    return sum(len(p.replace(" ", "")) for p in phonemes)


# ── Synthesis log ────────────────────────────────────────────────────────────

def _load_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    for line in LOG_FILE.read_text().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _append_log(phonemes: int, seconds: float, model: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {"phonemes": phonemes, "seconds": round(seconds, 2), "model": model}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _estimate_seconds(phonemes: int, model: str) -> float | None:
    """Return estimated synthesis time, or None if not enough data."""
    entries = [e for e in _load_log() if e.get("model") == model]
    if len(entries) < _MIN_SAMPLES_FOR_ESTIMATE:
        return None
    # Simple linear regression: seconds = a * phonemes + b
    n = len(entries)
    sx  = sum(e["phonemes"] for e in entries)
    sy  = sum(e["seconds"]  for e in entries)
    sxx = sum(e["phonemes"] ** 2           for e in entries)
    sxy = sum(e["phonemes"] * e["seconds"] for e in entries)
    denom = n * sxx - sx * sx
    if denom == 0:
        return sy / n  # all same phoneme count, return mean
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    est = a * phonemes + b
    return max(est, 1.0)


# ── Progress display ─────────────────────────────────────────────────────────

def _progress_bar(elapsed: float, total_est: float, width: int = 30) -> str:
    frac = min(elapsed / total_est, 1.0) if total_est > 0 else 0
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    return f"\r  [{bar}] {elapsed:.0f}s / ~{total_est:.0f}s"


def _progress_spinner(elapsed: float) -> str:
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    frame = frames[int(elapsed * 4) % len(frames)]
    return f"\r  {frame} Synthesizing... {elapsed:.0f}s"


# ── Speed adjustment ─────────────────────────────────────────────────────────

def adjust_speed(samples, speed: float):
    """Time-stretch audio using WSOLA (Waveform Similarity Overlap-Add).

    Preserves pitch while changing playback speed.  Unlike plain OLA,
    WSOLA cross-correlates each frame against the previous output to find
    the phase-aligned position, avoiding the muffled/phasy artefacts of
    naive overlap-add.

    speed > 1.0: faster (shorter audio, same pitch)
    speed < 1.0: slower (longer audio, same pitch)
    """
    import numpy as np
    if speed == 1.0:
        return samples

    samples = np.asarray(samples, dtype=np.float32)
    frame_size = 1024                               # ~43 ms at 24 kHz
    hop_a = frame_size // 4                         # analysis hop = 256 samples
    hop_s = max(1, int(round(hop_a / speed)))       # synthesis hop
    tolerance = frame_size // 2                     # WSOLA search radius

    window = np.hanning(frame_size).astype(np.float32)

    n_frames = max(1, (len(samples) - frame_size) // hop_a + 1)
    out_len = hop_s * n_frames + frame_size
    output = np.zeros(out_len, dtype=np.float32)
    norm   = np.zeros(out_len, dtype=np.float32)

    overlap = max(0, frame_size - hop_s)          # overlap between consecutive output frames
    prev_frame: np.ndarray | None = None

    for i in range(n_frames):
        s_start = i * hop_s

        if i == 0:
            best = 0
        else:
            # Base expected position on frame index (not accumulated offset)
            # to prevent drift from compounding across frames.
            expected = i * hop_a
            lo = max(0, expected - tolerance)
            hi = min(len(samples) - frame_size, expected + tolerance)
            if lo > hi:
                break

            if overlap > 0 and prev_frame is not None:
                # Correlate tail of previous input frame against the start
                # of each candidate — this is the region that will overlap
                # in the output, so phase-aligning here removes artefacts.
                ref = prev_frame[-overlap:]
                best_corr = -np.inf
                best = expected
                for candidate in range(lo, hi + 1):
                    seg = samples[candidate:candidate + overlap]
                    if len(seg) < overlap:
                        break
                    corr = np.dot(ref, seg)
                    if corr > best_corr:
                        best_corr = corr
                        best = candidate
            else:
                best = expected

        a_end = best + frame_size
        if a_end > len(samples):
            break

        frame = samples[best:a_end]
        prev_frame = frame
        output[s_start:s_start + frame_size] += frame * window
        norm  [s_start:s_start + frame_size] += window

    nonzero = norm > 1e-8
    output[nonzero] /= norm[nonzero]

    target_len = max(1, int(round(len(samples) / speed)))
    return output[:target_len]


# ── Public API ───────────────────────────────────────────────────────────────

def synthesize(
    text: str,
    output_path: str,
    *,
    model: str | None = None,
    voice: str | None = None,
    speed: float = 1.0,
) -> None:
    """Synthesize *text* and write a WAV file to *output_path*.

    Optional *model*, *voice*, and *speed* override the values from
    prefs.json for this invocation only (they do NOT write to prefs.json).

    Heavy imports (kittentts, soundfile) are deferred to this function so
    that importing the module does not load the TTS engine.
    """
    os.environ["HF_HUB_OFFLINE"] = "0"

    prefs       = _load_prefs()
    model_alias = model if model is not None else prefs.get("model", "mini")
    voice       = voice if voice is not None else prefs.get("voice", "Hugo")
    repo_id     = MODEL_REGISTRY.get(model_alias, MODEL_REGISTRY["mini"])
    cache_dir   = str(CACHE_DIR / model_alias)

    # Check if model needs downloading first
    model_cache = CACHE_DIR / model_alias
    if not model_cache.exists() or not any(model_cache.iterdir()):
        print(f"  Downloading '{model_alias}' model (first run — this may take a minute)...",
              file=sys.stderr)

    # Count phonemes (cheap) before loading the model
    phonemes = _count_phonemes(text)
    est = _estimate_seconds(phonemes, model_alias)

    import soundfile as sf
    from kittentts import KittenTTS
    import threading

    tts = KittenTTS(repo_id, cache_dir=cache_dir)

    if est is not None:
        print(f"  Synthesizing (~{est:.0f}s estimated)...", file=sys.stderr)
    else:
        print("  Synthesizing (this may take a while)...", file=sys.stderr)

    # Run generation in a thread so we can show progress on the main thread
    result: list = []
    error: list  = []

    def _generate():
        try:
            result.append(tts.generate(text, voice=voice, clean_text=False))
        except Exception as exc:
            error.append(exc)

    t = threading.Thread(target=_generate, daemon=True)
    t0 = time.monotonic()
    t.start()

    is_tty = sys.stderr.isatty()
    try:
        while t.is_alive():
            t.join(timeout=0.25)
            if is_tty:
                elapsed = time.monotonic() - t0
                if est is not None:
                    sys.stderr.write(_progress_bar(elapsed, est))
                else:
                    sys.stderr.write(_progress_spinner(elapsed))
                sys.stderr.flush()
    except KeyboardInterrupt:
        if is_tty:
            sys.stderr.write("\r" + " " * 60 + "\r")
            sys.stderr.flush()
        raise

    elapsed = time.monotonic() - t0

    if is_tty:
        # Clear the progress line
        sys.stderr.write("\r" + " " * 60 + "\r")
        sys.stderr.flush()

    if error:
        raise error[0]

    audio = result[0]
    if speed != 1.0:
        audio = adjust_speed(audio, speed)
    sf.write(output_path, audio, 24_000)
    _append_log(phonemes, elapsed, model_alias)
