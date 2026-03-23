"""
mew.speak — synthesize text to a WAV file via Kokoro TTS (ONNX).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlretrieve

from mew.config import DEFAULTS

# kokoro-onnx release assets (v1.0)
_KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
MODEL_REGISTRY = {
    "int8":  {"file": "kokoro-v1.0.int8.onnx",  "desc": "Compact (88 MB)",   "size_mb": 88},
    "fp16":  {"file": "kokoro-v1.0.fp16.onnx",  "desc": "Balanced (169 MB)",  "size_mb": 169},
    "fp32":  {"file": "kokoro-v1.0.onnx",        "desc": "Full precision (310 MB)", "size_mb": 310},
}
_VOICES_FILE = "voices-v1.0.bin"

PREFS_FILE = Path.home() / ".config" / "mew" / "prefs.json"
CACHE_DIR  = Path.home() / ".cache"  / "mew" / "models"
LOG_FILE   = Path.home() / ".local" / "share" / "mew" / "synthesis.jsonl"

_MIN_SAMPLES_FOR_ESTIMATE = 3

# Kokoro's native speed range — outside this, fall back to WSOLA.
_KOKORO_MIN_SPEED = 0.5
_KOKORO_MAX_SPEED = 2.0


def _load_prefs() -> dict:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


# ── Model file management ──────────────────────────────────────────────────

def _model_path(model_alias: str) -> Path:
    """Return the path to the ONNX model file for *model_alias*."""
    info = MODEL_REGISTRY.get(model_alias, MODEL_REGISTRY["int8"])
    return CACHE_DIR / info["file"]


def _voices_path() -> Path:
    return CACHE_DIR / _VOICES_FILE


def _download_file(url: str, dest: Path, label: str) -> None:
    """Download *url* to *dest* with a progress display."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")

    is_tty = sys.stderr.isatty()
    last_report = [0.0]

    def _reporthook(block_num, block_size, total_size):
        if not is_tty:
            return
        downloaded = block_num * block_size
        now = time.monotonic()
        if now - last_report[0] < 0.25 and downloaded < total_size:
            return
        last_report[0] = now
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            mb_done = downloaded / 1_048_576
            mb_total = total_size / 1_048_576
            sys.stderr.write(f"\r  {label}: {mb_done:.0f}/{mb_total:.0f} MB ({pct}%)")
        else:
            mb_done = downloaded / 1_048_576
            sys.stderr.write(f"\r  {label}: {mb_done:.0f} MB")
        sys.stderr.flush()

    try:
        urlretrieve(url, str(tmp), reporthook=_reporthook)
        tmp.rename(dest)
        if is_tty:
            sys.stderr.write(f"\r  \u2713 {label}" + " " * 30 + "\n")
            sys.stderr.flush()
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def ensure_model(model_alias: str) -> tuple[Path, Path]:
    """Return (model_path, voices_path), downloading if necessary."""
    mp = _model_path(model_alias)
    vp = _voices_path()

    if not mp.exists():
        info = MODEL_REGISTRY.get(model_alias, MODEL_REGISTRY["int8"])
        url = f"{_KOKORO_RELEASE}/{info['file']}"
        print(f"  Downloading Kokoro {model_alias} model (~{info['size_mb']} MB)...",
              file=sys.stderr)
        _download_file(url, mp, f"Kokoro {model_alias}")

    if not vp.exists():
        url = f"{_KOKORO_RELEASE}/{_VOICES_FILE}"
        print(f"  Downloading Kokoro voice data...", file=sys.stderr)
        _download_file(url, vp, "Voice data")

    return mp, vp


# ── Phoneme counting ────────────────────────────────────────────────────────

def _count_phonemes(text: str) -> int:
    """Count phonemes using the espeak backend."""
    import phonemizer
    backend = phonemizer.backend.EspeakBackend(
        language="en-us", preserve_punctuation=True, with_stress=True,
    )
    phonemes = backend.phonemize([text])
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


def _append_log(
    phonemes: int,
    seconds: float,
    model: str,
    speed_samples: int | None = None,
    speed_seconds: float | None = None,
) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry: dict = {"phonemes": phonemes, "seconds": round(seconds, 2), "model": model}
    if speed_samples is not None and speed_seconds is not None:
        entry["speed_samples"] = speed_samples
        entry["speed_seconds"] = round(speed_seconds, 3)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _estimate_seconds(phonemes: int, model: str) -> float | None:
    """Return estimated synthesis time, or None if not enough data."""
    entries = [e for e in _load_log() if e.get("model") == model]
    if len(entries) < _MIN_SAMPLES_FOR_ESTIMATE:
        return None
    n = len(entries)
    sx  = sum(e["phonemes"] for e in entries)
    sy  = sum(e["seconds"]  for e in entries)
    sxx = sum(e["phonemes"] ** 2           for e in entries)
    sxy = sum(e["phonemes"] * e["seconds"] for e in entries)
    denom = n * sxx - sx * sx
    if denom == 0:
        return sy / n
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    est = a * phonemes + b
    return max(est, 1.0)


def _estimate_speed_seconds(audio_samples: int) -> float | None:
    """Return estimated speed-adjustment time based on audio sample count, or None."""
    entries = [e for e in _load_log()
               if "speed_samples" in e and "speed_seconds" in e]
    if len(entries) < _MIN_SAMPLES_FOR_ESTIMATE:
        return None
    n   = len(entries)
    sx  = sum(e["speed_samples"] for e in entries)
    sy  = sum(e["speed_seconds"] for e in entries)
    sxx = sum(e["speed_samples"] ** 2                  for e in entries)
    sxy = sum(e["speed_samples"] * e["speed_seconds"]  for e in entries)
    denom = n * sxx - sx * sx
    if denom == 0:
        return sy / n
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return max(a * audio_samples + b, 0.1)


# ── Progress display ─────────────────────────────────────────────────────────

def _progress_bar(elapsed: float, total_est: float, label: str = "", width: int = 20) -> str:
    frac = min(elapsed / total_est, 1.0) if total_est > 0 else 0
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    prefix = f"  {label} " if label else "  "
    return f"\r{prefix}[{bar}] {elapsed:.0f}s / ~{total_est:.0f}s"


def _progress_spinner(elapsed: float, label: str = "") -> str:
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    frame = frames[int(elapsed * 4) % len(frames)]
    suffix = f" {label}..." if label else "..."
    return f"\r  {frame}{suffix} {elapsed:.0f}s"


def _run_stage(label: str, est: float | None, fn, *args):
    """Run fn(*args) in a background thread with live progress on stderr.

    Shows a spinner (est=None) or a progress bar (est given).
    On completion prints a persistent '✓ label  X.Xs' line.
    Returns (result, elapsed_seconds).
    """
    result: list = []
    error:  list = []

    def _worker():
        try:
            result.append(fn(*args))
        except Exception as exc:
            error.append(exc)

    t = threading.Thread(target=_worker, daemon=True)
    t0 = time.monotonic()
    t.start()

    is_tty = sys.stderr.isatty()
    try:
        while t.is_alive():
            t.join(timeout=0.25)
            if is_tty:
                elapsed = time.monotonic() - t0
                if est is not None:
                    sys.stderr.write(_progress_bar(elapsed, est, label))
                else:
                    sys.stderr.write(_progress_spinner(elapsed, label))
                sys.stderr.flush()
    except KeyboardInterrupt:
        if is_tty:
            sys.stderr.write("\r" + " " * 70 + "\r")
            sys.stderr.flush()
        raise

    elapsed = time.monotonic() - t0
    if is_tty:
        sys.stderr.write("\r" + " " * 70 + f"\r  \u2713 {label}  {elapsed:.1f}s\n")
        sys.stderr.flush()

    if error:
        raise error[0]
    return (result[0] if result else None), elapsed


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

    Heavy imports (kokoro_onnx, soundfile) are deferred to this function so
    that importing the module does not load the TTS engine.
    """
    prefs       = _load_prefs()
    model_alias = model if model is not None else prefs.get("model", DEFAULTS["model"])
    voice_id    = voice if voice is not None else prefs.get("voice", DEFAULTS["voice"])

    # Resolve friendly voice name → Kokoro voice ID if needed
    from mew.config import VOICE_REGISTRY
    if voice_id in VOICE_REGISTRY:
        voice_id = VOICE_REGISTRY[voice_id]

    # Ensure model files are present (download if needed)
    mp, vp = ensure_model(model_alias)

    # Defer heavy imports
    import soundfile as sf
    from kokoro_onnx import Kokoro

    # Stage 1: Phonemize — estimate scales with text length
    est_phonemize = max(2.0, len(text) / 2_000) if len(text) > 200 else None
    phonemes, _ = _run_stage("Phonemizing", est_phonemize, _count_phonemes, text)

    # Stage 2: Load model
    tts, _ = _run_stage(
        f"Loading model ({model_alias})", None,
        lambda: Kokoro(str(mp), str(vp)),
    )

    # Stage 3: Synthesize
    # Kokoro handles speed natively for 0.5–2.0; for >2.0, synthesize at 2.0
    # then WSOLA the remainder.
    kokoro_speed = min(speed, _KOKORO_MAX_SPEED)
    wsola_factor = speed / kokoro_speed if speed > _KOKORO_MAX_SPEED else None

    est_synth = _estimate_seconds(phonemes, model_alias)
    (audio, sample_rate), elapsed_synth = _run_stage(
        "Synthesizing", est_synth,
        lambda: tts.create(text, voice=voice_id, speed=kokoro_speed, lang="en-us"),
    )

    # Stage 4: WSOLA post-stretch (only for speeds > 2.0)
    speed_samples: int | None = None
    elapsed_speed: float | None = None
    if wsola_factor is not None and wsola_factor != 1.0:
        audio_samples = len(audio)
        est_speed = _estimate_speed_seconds(audio_samples) or max(0.5, audio_samples / sample_rate / 15)
        audio, elapsed_speed = _run_stage(
            f"Adjusting speed ({speed}×)", est_speed, adjust_speed, audio, wsola_factor,
        )
        speed_samples = audio_samples

    sf.write(output_path, audio, sample_rate)
    _append_log(phonemes, elapsed_synth, model_alias, speed_samples, elapsed_speed)
