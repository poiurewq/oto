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


# ── Public API ───────────────────────────────────────────────────────────────

def synthesize(
    text: str,
    output_path: str,
    *,
    model: str | None = None,
    voice: str | None = None,
) -> None:
    """Synthesize *text* and write a WAV file to *output_path*.

    Optional *model* and *voice* override the values from prefs.json for
    this invocation only (they do NOT write to prefs.json).

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

    t = threading.Thread(target=_generate)
    t0 = time.monotonic()
    t.start()

    is_tty = sys.stderr.isatty()
    while t.is_alive():
        t.join(timeout=0.25)
        if is_tty:
            elapsed = time.monotonic() - t0
            if est is not None:
                sys.stderr.write(_progress_bar(elapsed, est))
            else:
                sys.stderr.write(_progress_spinner(elapsed))
            sys.stderr.flush()

    elapsed = time.monotonic() - t0

    if is_tty:
        # Clear the progress line
        sys.stderr.write("\r" + " " * 60 + "\r")
        sys.stderr.flush()

    if error:
        raise error[0]

    sf.write(output_path, result[0], 24_000)
    _append_log(phonemes, elapsed, model_alias)
