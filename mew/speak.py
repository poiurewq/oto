"""
mew.speak — synthesize text to a WAV file via KittenTTS.
"""

import json
import os
from pathlib import Path

MODEL_REGISTRY = {
    "mini":      "KittenML/kitten-tts-mini-0.8",
    "micro":     "KittenML/kitten-tts-micro-0.8",
    "nano":      "KittenML/kitten-tts-nano-0.8",
    "nano-int8": "KittenML/kitten-tts-nano-0.8-int8",
}

PREFS_FILE = Path.home() / ".config" / "mew" / "prefs.json"
CACHE_DIR  = Path.home() / ".cache"  / "mew" / "models"


def _load_prefs() -> dict:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"model": "mini", "voice": "Hugo"}


def synthesize(text: str, output_path: str) -> None:
    """Synthesize *text* and write a WAV file to *output_path*.

    Heavy imports (kittentts, soundfile) are deferred to this function so
    that importing the module does not load the TTS engine.
    """
    os.environ["HF_HUB_OFFLINE"] = "0"

    import soundfile as sf
    from kittentts import KittenTTS

    prefs       = _load_prefs()
    model_alias = prefs.get("model", "mini")
    voice       = prefs.get("voice", "Hugo")
    repo_id     = MODEL_REGISTRY.get(model_alias, MODEL_REGISTRY["mini"])
    cache_dir   = str(CACHE_DIR / model_alias)

    tts   = KittenTTS(repo_id, cache_dir=cache_dir)
    audio = tts.generate(text, voice=voice, clean_text=False)
    sf.write(output_path, audio, 24_000)
