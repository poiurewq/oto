"""
mew.cli — entry point for the mew command.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mew import __version__

_SYNOPSIS = """\
Usage: mew [options] file [file ...]
       mew config [model|voice|playback|speed|show]

  Convert study notes to speech via Kokoro TTS.

Type 'mew -h' for full usage."""

_HELP = """\
Usage: mew [options] file [file ...]
       mew config [model|voice|playback|speed|show]

  Preprocess note files and synthesize them to speech via Kokoro TTS.

Subcommands:
  config           Interactively set model, voice, playback, and speed
  config model     Change model only
  config voice           Change voice only
  config voice --preview Auto-preview current voice, then change
  config playback        Change playback method only
  config speed     Change default speed only
  config delete    Delete a downloaded model
  config show      Print current settings

Options:
  -h, --help           Show this help message and exit
  -V, --version        Print version and exit
  -i, --intermediate   Preprocess only, write .mew.md (skip synthesis)
  -p, --preprocessed   Skip preprocessing, synthesize file directly
  -n, --dry-run        Preview preprocessed text + time estimate, no files
  -v, --voice VOICE    One-off voice override (does not change config)
  -m, --model MODEL    One-off model override (does not change config)
  -P, --play           Auto-play audio after synthesis
  -s, --speed SPEED    Playback speed multiplier 1.0–3.0 (default: 1.0)

Output (default):   file.mew.wav  (conflict: file.mew.2.wav, etc.)
Output (-i):        file.mew.md
Input  (-p):        expects an already-preprocessed file

Run 'man mew' for full documentation."""


def _play_audio(path: Path, method: str) -> None:
    """Play *path* using the configured playback method."""
    import subprocess
    if method == "app":
        cmd = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
        subprocess.Popen(cmd)
        return
    # terminal (blocking)
    cmd = ["afplay", str(path)] if sys.platform == "darwin" else ["aplay", str(path)]
    print("  \u25b6 Playing...", file=sys.stderr)
    try:
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        sys.exit(0)


def _deconflict(path: Path) -> Path:
    """Return path if it doesn't exist; otherwise notes.mew.wav -> notes.mew.2.wav, etc."""
    if not path.exists():
        return path
    stem = path.with_suffix("")  # strip final ext, e.g. notes.mew.wav -> notes.mew
    final_ext = path.suffix      # e.g. ".wav" or ".md"
    n = 2
    while True:
        candidate = stem.parent / f"{stem.name}.{n}{final_ext}"
        if not candidate.exists():
            return candidate
        n += 1


def _mew_stem(input_path: Path) -> Path:
    """Return the path with .mew inserted before the final extension removed.

    notes.md        -> notes.mew
    notes.mew.md    -> notes.mew   (already has .mew, strip the outer ext)
    """
    if input_path.suffixes[-2:] == [".mew", input_path.suffix]:
        # e.g. notes.mew.md -> strip the last suffix
        return input_path.with_suffix("")
    return input_path.with_suffix(".mew")


def _validate_voice(name: str) -> str | None:
    """Return the canonical voice name if valid (case-insensitive), else None."""
    from mew.config import VOICE_NAMES
    for v in VOICE_NAMES:
        if v.lower() == name.lower():
            return v
    return None


def _validate_model(alias: str) -> str | None:
    """Return the model alias if valid (exact match), else None."""
    from mew.config import MODEL_ALIASES
    if alias in MODEL_ALIASES:
        return alias
    return None


def main() -> None:
    args = sys.argv[1:]

    # ── config subcommand ─────────────────────────────────────────────────────
    if args and args[0] == "config":
        from mew import config
        config.main(args[1:])
        return

    # ── option parsing ────────────────────────────────────────────────────────
    mode = "default"  # "default" | "intermediate" | "preprocessed" | "dry-run"
    voice_override: str | None = None
    model_override: str | None = None
    play: bool = False
    speed_override: float | None = None
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-h", "--help"):
            print(_HELP)
            return
        if a in ("-V", "--version"):
            print(f"mew {__version__}")
            return
        if a in ("-i", "--intermediate"):
            mode = "intermediate"
            i += 1
            continue
        if a in ("-p", "--preprocessed"):
            mode = "preprocessed"
            i += 1
            continue
        if a in ("-n", "--dry-run"):
            mode = "dry-run"
            i += 1
            continue
        if a in ("-v", "--voice"):
            if i + 1 >= len(args):
                print("mew: --voice requires an argument", file=sys.stderr)
                sys.exit(1)
            voice_override = args[i + 1]
            i += 2
            continue
        if a in ("-m", "--model"):
            if i + 1 >= len(args):
                print("mew: --model requires an argument", file=sys.stderr)
                sys.exit(1)
            model_override = args[i + 1]
            i += 2
            continue
        if a in ("-P", "--play"):
            play = True
            i += 1
            continue
        if a in ("-s", "--speed"):
            if i + 1 >= len(args):
                print("mew: --speed requires an argument", file=sys.stderr)
                sys.exit(1)
            try:
                speed_override = float(args[i + 1])
            except ValueError:
                print(f"mew: --speed requires a number, got: {args[i + 1]!r}", file=sys.stderr)
                sys.exit(1)
            if not (1.0 <= speed_override <= 3.0):
                print(f"mew: --speed must be between 1.0 and 3.0, got: {speed_override}", file=sys.stderr)
                sys.exit(1)
            i += 2
            continue
        if a == "--":
            positional += args[i + 1:]
            break
        if a.startswith("-"):
            print(f"mew: unknown option: {a}", file=sys.stderr)
            print("Try 'mew -h' for usage.", file=sys.stderr)
            sys.exit(1)
        positional.append(a)
        i += 1

    # ── mutual exclusivity checks ─────────────────────────────────────────────
    flags_present = set()
    for a in args:
        if a in ("-i", "--intermediate"):
            flags_present.add("-i")
        elif a in ("-p", "--preprocessed"):
            flags_present.add("-p")
        elif a in ("-n", "--dry-run"):
            flags_present.add("-n")
        elif a in ("-P", "--play"):
            flags_present.add("-P")

    if "-i" in flags_present and "-p" in flags_present:
        print("mew: -i and -p are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if "-n" in flags_present and "-p" in flags_present:
        print("mew: --dry-run and -p are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if "-P" in flags_present and "-i" in flags_present:
        print("mew: --play and -i are mutually exclusive (no audio is produced with -i)", file=sys.stderr)
        sys.exit(1)

    # ── validate overrides ────────────────────────────────────────────────────
    if voice_override is not None:
        canonical = _validate_voice(voice_override)
        if canonical is None:
            from mew.config import VOICE_NAMES
            print(f"mew: unknown voice: '{voice_override}'", file=sys.stderr)
            print(f"  Valid voices: {', '.join(VOICE_NAMES)}", file=sys.stderr)
            sys.exit(1)
        voice_override = canonical

    if model_override is not None:
        canonical = _validate_model(model_override)
        if canonical is None:
            from mew.config import MODEL_ALIASES
            print(f"mew: unknown model: '{model_override}'", file=sys.stderr)
            print(f"  Valid models: {', '.join(MODEL_ALIASES)}", file=sys.stderr)
            sys.exit(1)
        model_override = canonical
        from mew.config import is_downloaded
        if not is_downloaded(model_override):
            print(
                f"mew: model '{model_override}' is not downloaded. "
                f"Run 'mew config model' to download it.",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── no-arg synopsis ───────────────────────────────────────────────────────
    if not positional:
        print(_SYNOPSIS)
        return

    # ── resolve speed and playback from prefs (with CLI overrides) ────────────
    from mew.config import load_prefs, DEFAULTS
    _prefs = load_prefs()
    speed: float = speed_override if speed_override is not None else _prefs.get("speed", DEFAULTS["speed"])
    playback_method: str = _prefs.get("playback", DEFAULTS["playback"])

    # ── process files ─────────────────────────────────────────────────────────
    multi = len(positional) > 1
    had_error = False

    try:
        for file_idx, filepath in enumerate(positional, 1):
            input_path = Path(filepath)

            if multi:
                print(f"[{file_idx}/{len(positional)}] {filepath}", file=sys.stderr)

            if not input_path.exists():
                print(f"mew: file not found: {input_path}", file=sys.stderr)
                had_error = True
                continue

            stem = _mew_stem(input_path)

            try:
                if mode == "dry-run":
                    _do_dry_run(input_path, model_override, voice_override, multi)
                elif mode == "intermediate":
                    _do_intermediate(input_path, stem)
                elif mode == "preprocessed":
                    _do_preprocessed(input_path, stem, model_override, voice_override, speed, play, playback_method)
                else:
                    _do_default(input_path, stem, model_override, voice_override, speed, play, playback_method)
            except Exception as exc:
                print(f"mew: error processing {filepath}: {exc}", file=sys.stderr)
                had_error = True
    except KeyboardInterrupt:
        print("\n  Cancelled.", file=sys.stderr)
        sys.exit(0)

    if had_error:
        sys.exit(1)


# ── Mode implementations ────────────────────────────────────────────────────

def _do_dry_run(
    input_path: Path,
    model_override: str | None,
    voice_override: str | None,
    multi: bool,
) -> None:
    """Print preprocessed text to stdout, estimate to stderr."""
    from mew import preprocess
    from mew import speak
    import tempfile, os

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp_path = tmp.name

    try:
        preprocess.process(str(input_path), tmp_path)
        text = Path(tmp_path).read_text(encoding="utf-8")
    finally:
        os.unlink(tmp_path)

    if multi:
        print(f"--- {input_path.name} ---", file=sys.stderr)

    # Print preprocessed text to stdout
    print(text, end="")

    # Estimate duration to stderr (only if tty)
    if sys.stderr.isatty():
        from mew.config import load_prefs, DEFAULTS
        prefs = load_prefs()
        model_alias = model_override if model_override else prefs.get("model", DEFAULTS["model"])
        voice_name = voice_override if voice_override else prefs.get("voice", DEFAULTS["voice"])
        try:
            phonemes = speak._count_phonemes(text)
            est = speak._estimate_seconds(phonemes, model_alias)
            if est is not None:
                print(f"  ~{est:.0f}s estimated ({model_alias}, {voice_name})",
                      file=sys.stderr)
            else:
                print(f"  duration unknown ({model_alias}, {voice_name})",
                      file=sys.stderr)
        except Exception:
            print(f"  duration unknown ({model_alias}, {voice_name})",
                  file=sys.stderr)


def _do_intermediate(input_path: Path, stem: Path) -> None:
    """Preprocess only, write .mew.md."""
    from mew import preprocess
    out_md = _deconflict(stem.with_suffix(".mew.md"))
    preprocess.process(str(input_path), str(out_md))
    print(out_md)


def _do_preprocessed(
    input_path: Path,
    stem: Path,
    model_override: str | None,
    voice_override: str | None,
    speed: float = 1.0,
    play: bool = False,
    playback_method: str = "terminal",
) -> None:
    """Skip preprocessing, synthesize directly."""
    from mew import speak
    out_wav = _deconflict(stem.with_suffix(".mew.wav"))
    speak.synthesize(
        input_path.read_text(encoding="utf-8"),
        str(out_wav),
        model=model_override,
        voice=voice_override,
        speed=speed,
    )
    print(out_wav)
    if play:
        _play_audio(out_wav, playback_method)


def _do_default(
    input_path: Path,
    stem: Path,
    model_override: str | None,
    voice_override: str | None,
    speed: float = 1.0,
    play: bool = False,
    playback_method: str = "terminal",
) -> None:
    """Preprocess + synthesize (default mode)."""
    from mew import preprocess, speak
    import tempfile, os

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp_path = tmp.name

    try:
        # Stage 0: Preprocessing — estimate scales with file size
        file_bytes = input_path.stat().st_size
        est_preprocess = max(0.2, file_bytes / 60_000)
        speak._run_stage(
            "Preprocessing", est_preprocess,
            preprocess.process, str(input_path), tmp_path,
        )
        out_wav = _deconflict(stem.with_suffix(".mew.wav"))
        speak.synthesize(
            Path(tmp_path).read_text(encoding="utf-8"),
            str(out_wav),
            model=model_override,
            voice=voice_override,
            speed=speed,
        )
    finally:
        os.unlink(tmp_path)

    print(out_wav)
    if play:
        _play_audio(out_wav, playback_method)
