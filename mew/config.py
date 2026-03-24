"""
mew.config — interactive model/voice/substitutions preference selector.

Usage (via CLI):
  mew config            interactive: optionally change model and voice
  mew config model      change model only
  mew config voice      change voice only
  mew config subs       manage text substitutions
  mew config delete     delete a downloaded model
  mew config show       print current settings and exit

Preferences are stored in ~/.config/mew/prefs.json.
Substitutions are stored in ~/.config/mew/substitutions.json.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

PREFS_FILE        = Path.home() / ".config" / "mew" / "prefs.json"
SUBSTITUTIONS_FILE = Path.home() / ".config" / "mew" / "substitutions.json"
CACHE_DIR          = Path.home() / ".cache"  / "mew" / "models"

MODEL_REGISTRY = {
    "int8":  {"file": "kokoro-v1.0.int8.onnx",  "desc": "Compact (88 MB)"},
    "fp16":  {"file": "kokoro-v1.0.fp16.onnx",  "desc": "Balanced (169 MB)"},
    "fp32":  {"file": "kokoro-v1.0.onnx",        "desc": "Full precision (310 MB)"},
}
MODEL_ALIASES = list(MODEL_REGISTRY.keys())

# Friendly voice names → Kokoro v1.0 voice IDs.
# A curated subset of the 30+ English voices — covering male/female, US/UK.
VOICE_REGISTRY = {
    # American female
    "Heart":    "af_heart",
    "Bella":    "af_bella",
    "Sarah":    "af_sarah",
    "Nova":     "af_nova",
    "Nicole":   "af_nicole",
    "Jessica":  "af_jessica",
    # American male
    "Adam":     "am_adam",
    "Michael":  "am_michael",
    "Eric":     "am_eric",
    "Liam":     "am_liam",
    # British female
    "Emma":     "bf_emma",
    "Alice":    "bf_alice",
    # British male
    "George":   "bm_george",
    "Daniel":   "bm_daniel",
}
VOICE_NAMES = list(VOICE_REGISTRY.keys())

PLAYBACK_OPTIONS = {
    "terminal": "Play in terminal via afplay/aplay",
    "app":      "Open in default audio player",
}

SPEED_PRESETS = [1.0, 1.25, 1.5, 2.0, 3.0]

DEFAULTS = {"model": "int8", "voice": "Adam", "playback": "terminal", "speed": 1.0}

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
    from mew.speak import _model_path, _voices_path
    return _model_path(alias).exists() and _voices_path().exists()

def download_model(alias: str) -> None:
    from mew.speak import ensure_model
    ensure_model(alias)
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
            # Derive gender/accent from voice ID prefix
            prefix = code[:2]
            accent = "American" if prefix[0] == "a" else "British"
            gender = "female" if prefix[1] == "f" else "male"
            marker = "  ← current" if name == prefs["voice"] else ""
            print(f"  {i:>2}. {name:<10}  ({accent} {gender}){marker}")
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
    desc  = MODEL_REGISTRY.get(model, {}).get("desc", "unknown")
    print(f"model    : {model}  ({desc})")
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

        # Delete the specific model file, not the entire cache directory
        from mew.speak import _model_path
        mp = _model_path(chosen)
        if mp.exists():
            mp.unlink()
        print(f"  Model '{chosen}' deleted.")
        return


# ── Substitutions ────────────────────────────────────────────────────────────

_SEED_SUBSTITUTIONS = [
    # ── Titles & honorifics ──────────────────────────────────────────────
    {"find": r"\bDr\.",   "replace": "Doctor",    "regex": True, "first_only": False, "comment": "title"},
    {"find": r"\bMr\.",   "replace": "Mister",    "regex": True, "first_only": False, "comment": "title"},
    {"find": r"\bMrs\.",  "replace": "Missus",    "regex": True, "first_only": False, "comment": "title"},
    {"find": r"\bMs\.",   "replace": "Miz",       "regex": True, "first_only": False, "comment": "title"},
    {"find": r"\bProf\.", "replace": "Professor", "regex": True, "first_only": False, "comment": "title"},
    # ── Common written shorthand ─────────────────────────────────────────
    {"find": "vs.",       "replace": "versus",         "regex": False, "first_only": False},
    {"find": "approx.",   "replace": "approximately",  "regex": False, "first_only": False},
    {"find": "dept.",     "replace": "department",     "regex": False, "first_only": False},
    {"find": "govt.",     "replace": "government",     "regex": False, "first_only": False},
    {"find": "w/o",       "replace": "without",        "regex": False, "first_only": False, "comment": "must precede w/"},
    {"find": r"(?<!\w)w/(?!\w)", "replace": "with",    "regex": True,  "first_only": False},
    # ── Letter-acronyms TTS often mispronounces as words ─────────────────
    {"find": r"\bCEO\b",  "replace": "C.E.O.",  "regex": True, "first_only": False, "comment": "spell out"},
    {"find": r"\bCFO\b",  "replace": "C.F.O.",  "regex": True, "first_only": False, "comment": "spell out"},
    {"find": r"\bCTO\b",  "replace": "C.T.O.",  "regex": True, "first_only": False, "comment": "spell out"},
    {"find": r"\bPhD\b",  "replace": "P.H.D.",  "regex": True, "first_only": False, "comment": "spell out"},
    {"find": r"\bDIY\b",  "replace": "D.I.Y.",  "regex": True, "first_only": False, "comment": "spell out"},
    {"find": r"\bFAQ\b",  "replace": "F.A.Q.",  "regex": True, "first_only": False, "comment": "spell out"},
]


def ensure_substitutions_seeded() -> None:
    """Create substitutions.json with seed entries if it doesn't exist yet."""
    if SUBSTITUTIONS_FILE.exists():
        return
    _save_substitutions(list(_SEED_SUBSTITUTIONS))


def _load_substitutions() -> list[dict]:
    """Load substitutions.json, returning [] if absent or malformed."""
    if not SUBSTITUTIONS_FILE.exists():
        return []
    try:
        data = json.loads(SUBSTITUTIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data


def _save_substitutions(subs: list[dict]) -> None:
    SUBSTITUTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBSTITUTIONS_FILE.write_text(json.dumps(subs, indent=2) + "\n")


def _fmt_sub(entry: dict, idx: int) -> str:
    """Format a single substitution entry for display."""
    find = entry.get("find", "")
    replace = entry.get("replace", "")
    kind = "regex" if entry.get("regex") else "literal"
    mode = "first only" if entry.get("first_only") else "all"
    comment = entry.get("comment", "")
    suffix = f"  # {comment}" if comment else ""
    return f"  {idx}. {find!r} → {replace!r}  ({kind}, {mode}){suffix}"


def cmd_substitutions(prefs: dict) -> None:
    """Interactive CRUD for ~/.config/mew/substitutions.json."""
    import re as _re

    ensure_substitutions_seeded()
    subs = _load_substitutions()

    while True:
        print(f"\nSubstitutions ({len(subs)} entries):")
        if subs:
            for i, entry in enumerate(subs, 1):
                print(_fmt_sub(entry, i))
        else:
            print("  (none)")
        print()
        print("  a. Add entry")
        if subs:
            print("  e. Edit entry")
            print("  d. Delete entry")
        print()
        raw = input("Choose [a/e/d, or Enter to exit]: ").strip().lower()
        if not raw:
            return
        if raw == "a":
            entry = _prompt_sub_entry()
            if entry is not None:
                subs.append(entry)
                _save_substitutions(subs)
                print("  Added.")
        elif raw == "e" and subs:
            idx = _prompt_index("Edit", len(subs))
            if idx is not None:
                updated = _prompt_sub_entry(subs[idx])
                if updated is not None:
                    subs[idx] = updated
                    _save_substitutions(subs)
                    print("  Updated.")
        elif raw == "d" and subs:
            idx = _prompt_index("Delete", len(subs))
            if idx is not None:
                print(f"  Will delete: {_fmt_sub(subs[idx], idx + 1)}")
                yn = input("  Confirm? [y/N]: ").strip().lower()
                if yn in ("y", "yes"):
                    subs.pop(idx)
                    _save_substitutions(subs)
                    print("  Deleted.")
        else:
            print("  Invalid choice.")


def _prompt_index(action: str, count: int) -> int | None:
    """Prompt for a 1-based index, return 0-based or None."""
    raw = input(f"  {action} which entry? [1–{count}, or Enter to cancel]: ").strip()
    if not raw:
        return None
    if raw.isdigit():
        n = int(raw)
        if 1 <= n <= count:
            return n - 1
    print(f"  Please enter a number (1–{count}).")
    return None


def _prompt_sub_entry(existing: dict | None = None) -> dict | None:
    """Prompt for substitution fields. Returns dict or None if cancelled.

    If *existing* is provided, Enter keeps the current value for each field.
    """
    import re as _re

    is_edit = existing is not None
    defaults = existing or {}

    # find
    prompt = f"  find [{defaults.get('find', '')}]: " if is_edit else "  find: "
    find = input(prompt).strip()
    if is_edit and not find:
        find = defaults.get("find", "")
    if not find:
        print("  Cancelled (empty find).")
        return None

    # replace
    prompt = f"  replace [{defaults.get('replace', '')}]: " if is_edit else "  replace: "
    replace = input(prompt)
    if is_edit and replace == "":
        replace = defaults.get("replace", "")

    # regex flag
    cur_regex = defaults.get("regex", False)
    default_label = "Y/n" if cur_regex else "y/N"
    raw = input(f"  regex? [{default_label}]: ").strip().lower()
    if raw in ("y", "yes"):
        is_regex = True
    elif raw in ("n", "no"):
        is_regex = False
    else:
        is_regex = cur_regex

    # Validate regex
    if is_regex:
        try:
            _re.compile(find)
        except _re.error as exc:
            print(f"  Invalid regex: {exc}")
            return None

    # first_only flag
    cur_first = defaults.get("first_only", False)
    default_label = "Y/n" if cur_first else "y/N"
    raw = input(f"  first occurrence only? [{default_label}]: ").strip().lower()
    if raw in ("y", "yes"):
        first_only = True
    elif raw in ("n", "no"):
        first_only = False
    else:
        first_only = cur_first

    return {"find": find, "replace": replace, "regex": is_regex, "first_only": first_only}


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
    elif subcmd in ("substitutions", "subs"):
        cmd_substitutions(prefs)
        return
    elif subcmd == "delete":
        cmd_delete(prefs)
        return
    else:
        _menu = [
            ("model",    "Change model",              cmd_model),
            ("voice",    "Change voice",               cmd_voice),
            ("playback", "Change playback method",    cmd_playback),
            ("speed",    "Change default speed",      cmd_speed),
            ("subs",     "Manage text substitutions", cmd_substitutions),
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
