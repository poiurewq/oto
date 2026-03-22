"""
mew.cli — entry point for the mew command.
"""

import sys
from pathlib import Path

from mew import __version__

_SYNOPSIS = """\
Usage: mew [options] file
       mew config [model|voice|show]

  Convert a study note to speech via KittenTTS.

Type 'mew --help' for full usage."""

_HELP = """\
Usage: mew [options] file
       mew config [model|voice|show]

  Preprocess a note file and synthesize it to speech via KittenTTS.

Subcommands:
  config          Interactively set model and voice preferences
  config model    Change model only
  config voice    Change voice only
  config delete   Delete a downloaded model
  config show     Print current model and voice settings

Options:
  -h, --help      Show this help message and exit
      --version   Print version and exit

Output files (written alongside the input):
  file-processed.md   Preprocessed plain text, kept for inspection
  file-processed.wav  Synthesized audio

Run 'man mew' for full documentation."""


def main() -> None:
    args = sys.argv[1:]

    # ── config subcommand ─────────────────────────────────────────────────────
    if args and args[0] == "config":
        from mew import config
        config.main(args[1:])
        return

    # ── option parsing ────────────────────────────────────────────────────────
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-h", "--help"):
            print(_HELP)
            return
        if a == "--version":
            print(f"mew {__version__}")
            return
        if a == "--":
            positional += args[i + 1:]
            break
        if a.startswith("-"):
            print(f"mew: unknown option: {a}", file=sys.stderr)
            print("Try 'mew --help' for usage.", file=sys.stderr)
            sys.exit(1)
        positional.append(a)
        i += 1

    # ── no-arg synopsis ───────────────────────────────────────────────────────
    if not positional:
        print(_SYNOPSIS)
        return

    if len(positional) != 1:
        print("mew: expected exactly one argument", file=sys.stderr)
        print("Try 'mew --help' for usage.", file=sys.stderr)
        sys.exit(1)

    input_path = Path(positional[0])

    if not input_path.exists():
        print(f"mew: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # ── Step 1: preprocess ────────────────────────────────────────────────────
    from mew import preprocess
    print(f"→ Preprocessing: {input_path}")
    processed_md = Path(preprocess.process(str(input_path)))
    print(f"  Written: {processed_md}")

    # ── Step 2: synthesize ────────────────────────────────────────────────────
    from mew import speak
    processed_wav = processed_md.with_suffix(".wav")
    print(f"→ Synthesizing:  {processed_wav}")
    speak.synthesize(processed_md.read_text(encoding="utf-8"), str(processed_wav))
    print(f"✓ Done: {processed_wav}")
