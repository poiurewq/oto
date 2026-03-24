# mew

Preprocess Markdown study notes and synthesize speech via Kokoro TTS.

## Local development

### Testing local changes (no install needed)

Use the `dev` wrapper script, which runs your local source against the
brew venv (dependencies + espeak):

```sh
./dev --dry-run yourfile.md
./dev -v Luna yourfile.md
./dev file1.md file2.md
```

Any edits to the source take effect immediately — no reinstall needed.
The brew-installed version at `$(brew --prefix)/bin/mew` remains untouched.

## Uninstalling

`brew uninstall mew` removes the formula but leaves three directories behind:

```sh
brew uninstall mew
rm -rf /opt/homebrew/var/mew/venv   # Python environment
rm -rf ~/.config/mew                # user preferences
rm -rf ~/.cache/mew                 # downloaded model files
```

### Running tests

Tests only exercise preprocessing and CLI logic (no TTS dependencies needed),
so system Python works fine:

```sh
python3.12 -m unittest test_cli -v          # CLI tests
python3.12 -m unittest test_preprocess -v   # preprocessing tests
python3.12 -m unittest discover -v          # all tests
```
