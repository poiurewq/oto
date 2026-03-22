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

DEFAULTS = {"model": "mini", "voice": "Hugo"}


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
    print(f"  Downloading '{alias}' from {repo} ...")
    KittenTTS(repo, cache_dir=cache)
    print(f"  Model '{alias}' ready.")


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
    print("\nAvailable voices:")
    for i, name in enumerate(VOICE_NAMES, 1):
        code   = VOICE_REGISTRY[name]
        gender = "female" if code.endswith("-f") else "male"
        marker = "  ← current" if name == prefs["voice"] else ""
        print(f"  {i}. {name:<8}  ({gender}){marker}")
    print()
    while True:
        raw = input(
            f"Choose voice [1–{len(VOICE_NAMES)}, name, or Enter to keep '{prefs['voice']}']: "
        ).strip()
        if not raw:
            return prefs["voice"]
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(VOICE_NAMES):
                return VOICE_NAMES[n - 1]
        for name in VOICE_NAMES:
            if name.lower() == raw.lower():
                return name
        print(f"  Please enter a number (1–{len(VOICE_NAMES)}) or a voice name.")


# ── Subcommand implementations ────────────────────────────────────────────────

def cmd_show(prefs: dict) -> None:
    model = prefs.get("model", DEFAULTS["model"])
    voice = prefs.get("voice", DEFAULTS["voice"])
    code  = VOICE_REGISTRY.get(voice, voice)
    repo  = MODEL_REGISTRY.get(model, {}).get("repo", "unknown")
    print(f"model : {model}  ({repo})")
    print(f"voice : {voice}  ({code})")

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

def cmd_voice(prefs: dict) -> None:
    chosen = select_voice(prefs)
    if chosen == prefs["voice"]:
        print(f"  Voice unchanged ('{chosen}').")
        return
    prefs["voice"] = chosen
    save_prefs(prefs)
    print(f"  Voice set to '{chosen}'.")

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
        cmd_voice(prefs)
    elif subcmd == "delete":
        cmd_delete(prefs)
        return
    else:
        yn = input("\nChange model? [y/N]: ").strip().lower()
        if yn in ("y", "yes"):
            cmd_model(prefs)
        yn = input("\nChange voice? [y/N]: ").strip().lower()
        if yn in ("y", "yes"):
            cmd_voice(prefs)
        yn = input("\nDelete a model? [y/N]: ").strip().lower()
        if yn in ("y", "yes"):
            cmd_delete(prefs)
            return

    print("\nCurrent settings:")
    cmd_show(load_prefs())


if __name__ == "__main__":
    main()
