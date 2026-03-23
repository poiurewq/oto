"""
mew.config — interactive model/voice preference selector.

Usage (via CLI):
  mew config            interactive: optionally change model and voice
  mew config model      change model only
  mew config voice      change voice only
  mew config delete     delete a downloaded model
  mew config show       print current settings and exit

Preferences are stored in ~/.config/mew/prefs.json.
"""

import json
import os
import shutil
from pathlib import Path

PREFS_FILE = Path.home() / ".config" / "mew" / "prefs.json"
CACHE_DIR  = Path.home() / ".cache"  / "mew" / "models"

MODEL_REGISTRY = {
    "mini":      {"repo": "KittenML/kitten-tts-mini-0.8",      "desc": "Best quality"},
    "micro":     {"repo": "KittenML/kitten-tts-micro-0.8",     "desc": "Balanced"},
    "nano":      {"repo": "KittenML/kitten-tts-nano-0.8",      "desc": "Fast, compact"},
    "nano-int8": {"repo": "KittenML/kitten-tts-nano-0.8-int8", "desc": "Fast, quantized"},
}
MODEL_ALIASES = list(MODEL_REGISTRY.keys())

# Friendly voice names → internal codes (same across all 0.8-series models)
VOICE_REGISTRY = {
    "Bella":  "expr-voice-2-f",
    "Jasper": "expr-voice-2-m",
    "Luna":   "expr-voice-3-f",
    "Bruno":  "expr-voice-3-m",
    "Rosie":  "expr-voice-4-f",
    "Hugo":   "expr-voice-4-m",
    "Kiki":   "expr-voice-5-f",
    "Leo":    "expr-voice-5-m",
}
VOICE_NAMES = list(VOICE_REGISTRY.keys())

PLAYBACK_OPTIONS = {
    "terminal": "Play in terminal via afplay/aplay",
    "app":      "Open in default audio player",
}

SPEED_PRESETS = [1.0, 1.25, 1.5, 2.0, 3.0]

DEFAULTS = {"model": "micro", "voice": "Bruno", "playback": "terminal", "speed": 1.0}

PREVIEW_TEXT = "Here is a preview of this voice."


# ── Prefs I/O ─────────────────────────────────────────────────────────────────

def load_prefs() -> dict:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)

def save_prefs(prefs: dict) -> None:
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREFS_FILE.write_text(json.dumps(prefs, indent=2) + "\n")


# ── Model helpers ─────────────────────────────────────────────────────────────

def is_downloaded(alias: str) -> bool:
    model_cache = CACHE_DIR / alias
    return model_cache.exists() and any(model_cache.iterdir())

def download_model(alias: str) -> None:
    os.environ["HF_HUB_OFFLINE"] = "0"
    from kittentts import KittenTTS
    repo  = MODEL_REGISTRY[alias]["repo"]
    cache = str(CACHE_DIR / alias)
    print(f"  Downloading '{alias}' from {repo}...")
    print(f"  This may take a minute depending on your connection.")
    KittenTTS(repo, cache_dir=cache)
    print(f"  Model '{alias}' ready.")


# ── Playback / preview helpers ────────────────────────────────────────────────

def _play_audio(path, method: str) -> None:
    """Play *path* using the configured playback method."""
    import subprocess, sys
    if method == "app":
        cmd = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
        subprocess.Popen(cmd)
        return
    cmd = ["afplay", str(path)] if sys.platform == "darwin" else ["aplay", str(path)]
    try:
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        proc.kill()


def _preview_voice(voice_name: str, prefs: dict) -> None:
    """Synthesize PREVIEW_TEXT with *voice_name* to a temp WAV and play it."""
    import os, sys, tempfile
    from mew import speak

    model    = prefs.get("model",    DEFAULTS["model"])
    playback = prefs.get("playback", DEFAULTS["playback"])

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
    try:
        print(f"  Previewing '{voice_name}'...", file=sys.stderr)
        speak.synthesize(PREVIEW_TEXT, tmp_path, model=model, voice=voice_name)
        _play_audio(tmp_path, playback)
    finally:
        if playback != "app" and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ── Interactive selectors ─────────────────────────────────────────────────────

def select_model(prefs: dict) -> str:
    print("\nAvailable models:")
    col = max(len(a) for a in MODEL_ALIASES)
    for i, alias in enumerate(MODEL_ALIASES, 1):
        info   = MODEL_REGISTRY[alias]
        status = "[downloaded]" if is_downloaded(alias) else "[not downloaded]"
        marker = "  ← current" if alias == prefs["model"] else ""
        print(f"  {i}. {alias:<{col}}  {status:<16}  {info['desc']}{marker}")
    print()
    while True:
        raw = input(
            f"Choose model [1–{len(MODEL_ALIASES)}, name, or Enter to keep '{prefs['model']}']: "
        ).strip()
        if not raw:
            return prefs["model"]
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(MODEL_ALIASES):
                return MODEL_ALIASES[n - 1]
        if raw in MODEL_REGISTRY:
            return raw
        print(f"  Please enter a number (1–{len(MODEL_ALIASES)}) or a model name.")

def select_voice(prefs: dict) -> str:
    while True:
        print("\nAvailable voices:")
        for i, name in enumerate(VOICE_NAMES, 1):
            code   = VOICE_REGISTRY[name]
            gender = "female" if code.endswith("-f") else "male"
            marker = "  ← current" if name == prefs["voice"] else ""
            print(f"  {i}. {name:<8}  ({gender}){marker}")
        print()
        raw = input(
            f"Choose voice [1–{len(VOICE_NAMES)}, name, p to preview, "
            f"or Enter to keep '{prefs['voice']}']: "
        ).strip()
        if not raw:
            return prefs["voice"]
        if raw.lower() == "p":
            _do_voice_preview(prefs)
            continue
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(VOICE_NAMES):
                return VOICE_NAMES[n - 1]
        for name in VOICE_NAMES:
            if name.lower() == raw.lower():
                return name
        print(f"  Please enter a number (1–{len(VOICE_NAMES)}), a voice name, or 'p' to preview.")


def _do_voice_preview(prefs: dict) -> None:
    """Prompt for a voice to preview, synthesize, play, return."""
    while True:
        praw = input(
            f"  Preview which voice? [1–{len(VOICE_NAMES)}, name, or Enter to cancel]: "
        ).strip()
        if not praw:
            return
        preview_name = None
        if praw.isdigit():
            n = int(praw)
            if 1 <= n <= len(VOICE_NAMES):
                preview_name = VOICE_NAMES[n - 1]
        if preview_name is None:
            for name in VOICE_NAMES:
                if name.lower() == praw.lower():
                    preview_name = name
                    break
        if preview_name is not None:
            _preview_voice(preview_name, prefs)
            return
        print(f"  Please enter a number (1–{len(VOICE_NAMES)}) or a voice name.")


def select_playback(prefs: dict) -> str:
    current = prefs.get("playback", DEFAULTS["playback"])
    options = list(PLAYBACK_OPTIONS.items())
    print(f"\nCurrent playback method: {current} ({PLAYBACK_OPTIONS.get(current, '?')})")
    print()
    for i, (key, desc) in enumerate(options, 1):
        marker = "  ← current" if key == current else ""
        print(f"  {i}. {key:<10}  {desc}{marker}")
    print()
    while True:
        raw = input(
            f"Choose [1-{len(options)}, or Enter to keep '{current}']: "
        ).strip()
        if not raw:
            return current
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(options):
                return options[n - 1][0]
        if raw in PLAYBACK_OPTIONS:
            return raw
        print(f"  Please enter a number (1–{len(options)}) or a playback method name.")


def select_speed(prefs: dict) -> float:
    current = prefs.get("speed", DEFAULTS["speed"])
    print(f"\nCurrent default speed: {current}x")
    print()
    labels = {
        1.0:  "Normal",
        1.25: "Slightly faster",
        1.5:  "Faster",
        2.0:  "Double speed",
        3.0:  "Triple speed",
    }
    for i, preset in enumerate(SPEED_PRESETS, 1):
        marker = "  ← current" if preset == current else ""
        print(f"  {i}. {str(preset) + 'x':<6}  {labels.get(preset, '')}{marker}")
    print()
    while True:
        raw = input(
            f"Choose [1-{len(SPEED_PRESETS)}, or Enter to keep '{current}x']: "
        ).strip()
        if not raw:
            return current
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(SPEED_PRESETS):
                return SPEED_PRESETS[n - 1]
        print(f"  Please enter a number (1–{len(SPEED_PRESETS)}).")


# ── Subcommand implementations ────────────────────────────────────────────────

def cmd_show(prefs: dict) -> None:
    model    = prefs.get("model",    DEFAULTS["model"])
    voice    = prefs.get("voice",    DEFAULTS["voice"])
    playback = prefs.get("playback", DEFAULTS["playback"])
    speed    = prefs.get("speed",    DEFAULTS["speed"])
    code  = VOICE_REGISTRY.get(voice, voice)
    repo  = MODEL_REGISTRY.get(model, {}).get("repo", "unknown")
    print(f"model    : {model}  ({repo})")
    print(f"voice    : {voice}  ({code})")
    print(f"playback : {playback}  ({PLAYBACK_OPTIONS.get(playback, '?')})")
    print(f"speed    : {speed}x")

def cmd_model(prefs: dict) -> None:
    chosen = select_model(prefs)
    if chosen == prefs["model"]:
        print(f"  Model unchanged ('{chosen}').")
        return
    if not is_downloaded(chosen):
        yn = input(f"\n  '{chosen}' is not downloaded. Download now? [Y/n]: ").strip().lower()
        if yn in ("", "y", "yes"):
            download_model(chosen)
        else:
            print("  Download skipped. Model not changed.")
            return
    prefs["model"] = chosen
    save_prefs(prefs)
    print(f"  Model set to '{chosen}'.")

def cmd_voice(prefs: dict, preview: bool = False) -> None:
    if preview:
        current = prefs.get("voice", DEFAULTS["voice"])
        print(f"  Auto-previewing current voice: {current}")
        _preview_voice(current, prefs)
    chosen = select_voice(prefs)
    if chosen == prefs["voice"]:
        print(f"  Voice unchanged ('{chosen}').")
        return
    prefs["voice"] = chosen
    save_prefs(prefs)
    print(f"  Voice set to '{chosen}'.")

def cmd_playback(prefs: dict) -> None:
    chosen = select_playback(prefs)
    if chosen == prefs.get("playback", DEFAULTS["playback"]):
        print(f"  Playback method unchanged ('{chosen}').")
        return
    prefs["playback"] = chosen
    save_prefs(prefs)
    print(f"  Playback method set to '{chosen}'.")

def cmd_speed(prefs: dict) -> None:
    chosen = select_speed(prefs)
    if chosen == prefs.get("speed", DEFAULTS["speed"]):
        print(f"  Speed unchanged ({chosen}x).")
        return
    prefs["speed"] = chosen
    save_prefs(prefs)
    print(f"  Default speed set to {chosen}x.")

def cmd_delete(prefs: dict) -> None:
    downloaded = [a for a in MODEL_ALIASES if is_downloaded(a)]
    if not downloaded:
        print("  No models are currently downloaded.")
        return

    print("\nDownloaded models:")
    col = max(len(a) for a in downloaded)
    for i, alias in enumerate(downloaded, 1):
        marker = "  ← active" if alias == prefs["model"] else ""
        print(f"  {i}. {alias:<{col}}  {MODEL_REGISTRY[alias]['desc']}{marker}")
    print()

    while True:
        raw = input(
            f"Choose model to delete [1–{len(downloaded)}, name, or Enter to cancel]: "
        ).strip()
        if not raw:
            print("  Cancelled.")
            return
        chosen = None
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(downloaded):
                chosen = downloaded[n - 1]
        if chosen is None:
            for alias in downloaded:
                if alias.lower() == raw.lower():
                    chosen = alias
                    break
        if chosen is None:
            print(f"  Please enter a number (1–{len(downloaded)}) or a model name.")
            continue

        if chosen == prefs["model"]:
            print(f"\n  Warning: '{chosen}' is your active model.")
            print("  After deletion, mew will fail until you download another model.")
        yn = input(f"  Delete '{chosen}'? [y/N]: ").strip().lower()
        if yn not in ("y", "yes"):
            print("  Cancelled.")
            return

        shutil.rmtree(str(CACHE_DIR / chosen))
        print(f"  Model '{chosen}' deleted.")
        return


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args: list[str] | None = None) -> None:
    """Run the config subcommand.

    *args* is the list of arguments after 'config' (e.g. ['model'] or []).
    Defaults to sys.argv[1:] when called directly.
    """
    if args is None:
        import sys
        args = sys.argv[1:]

    try:
        _run(args)
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")


def _run(args: list[str]) -> None:
    prefs  = load_prefs()
    subcmd = args[0] if args else None

    if subcmd == "show":
        cmd_show(prefs)
        return

    print("Current settings:")
    cmd_show(prefs)

    if subcmd == "model":
        cmd_model(prefs)
    elif subcmd == "voice":
        cmd_voice(prefs, preview="--preview" in args[1:])
    elif subcmd == "playback":
        cmd_playback(prefs)
    elif subcmd == "speed":
        cmd_speed(prefs)
    elif subcmd == "delete":
        cmd_delete(prefs)
        return
    else:
        _menu = [
            ("model",    "Change model",              cmd_model),
            ("voice",    "Change voice",               cmd_voice),
            ("playback", "Change playback method",    cmd_playback),
            ("speed",    "Change default speed",      cmd_speed),
            ("delete",   "Delete a downloaded model", cmd_delete),
        ]
        while True:
            print("\nWhat would you like to change?\n")
            for i, (_, label, _fn) in enumerate(_menu, 1):
                print(f"  {i}. {label}")
            print()
            raw = input(f"Choose [1-{len(_menu)}, or Enter to exit]: ").strip()
            if not raw:
                return
            if raw.isdigit() and 1 <= int(raw) <= len(_menu):
                _, _, fn = _menu[int(raw) - 1]
                fn(prefs)
                prefs = load_prefs()
                print("\nCurrent settings:")
                cmd_show(prefs)
            else:
                print("  Invalid choice.")
        return

    print("\nCurrent settings:")
    cmd_show(load_prefs())


if __name__ == "__main__":
    main()
