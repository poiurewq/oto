#!/usr/bin/env python3
"""
test_cli.py — Unit and integration tests for mew.cli (Phase 1)

Run with:
    python3 -m pytest test_cli.py -v
    python3 -m pytest test_cli.py::TestFlagParsing -v
    python3 -m pytest test_cli.py::TestDryRun -v
"""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


# ── Test helpers ─────────────────────────────────────────────────────────────

def _run_cli(args: list[str], mock_synth=True) -> tuple[str, str, int]:
    """Run cli.main() with given args, return (stdout, stderr, exit_code)."""
    out, err = io.StringIO(), io.StringIO()
    exit_code = 0
    with mock.patch('sys.argv', ['mew'] + args), \
         mock.patch('sys.stdout', out), \
         mock.patch('sys.stderr', err):
        if mock_synth:
            with mock.patch('mew.speak.synthesize'):
                try:
                    from mew.cli import main
                    main()
                except SystemExit as e:
                    exit_code = e.code if e.code is not None else 0
        else:
            try:
                from mew.cli import main
                main()
            except SystemExit as e:
                exit_code = e.code if e.code is not None else 0
    return out.getvalue(), err.getvalue(), exit_code


# ── Flag parsing ─────────────────────────────────────────────────────────────

class TestFlagParsing(unittest.TestCase):
    """Test that cli.main() parses flags correctly."""

    def test_help_short(self):
        out, _, code = _run_cli(['-h'])
        self.assertEqual(code, 0)
        self.assertIn('--dry-run', out)

    def test_help_long(self):
        out, _, code = _run_cli(['--help'])
        self.assertEqual(code, 0)
        self.assertIn('--dry-run', out)

    def test_version_short(self):
        out, _, code = _run_cli(['-V'])
        self.assertEqual(code, 0)
        self.assertIn('mew', out)

    def test_version_long(self):
        out, _, code = _run_cli(['--version'])
        self.assertEqual(code, 0)
        self.assertIn('mew', out)

    def test_version_short_and_long_match(self):
        out_short, _, _ = _run_cli(['-V'])
        out_long, _, _ = _run_cli(['--version'])
        self.assertEqual(out_short, out_long)

    def test_unknown_option_exits_1(self):
        _, err, code = _run_cli(['--banana'])
        self.assertEqual(code, 1)
        self.assertIn('unknown option', err)

    def test_intermediate_long(self):
        """--intermediate should be accepted like -i."""
        with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
            f.write('Hello world.')
            tmp = f.name
        try:
            out, _, code = _run_cli(['--intermediate', tmp])
            self.assertEqual(code, 0)
            out_path = out.strip()
            self.assertTrue(out_path.endswith('.mew.md'))
            if os.path.exists(out_path):
                os.unlink(out_path)
        finally:
            os.unlink(tmp)

    def test_preprocessed_long(self):
        """--preprocessed should be accepted like -p."""
        with tempfile.NamedTemporaryFile(suffix='.mew.md', mode='w', delete=False) as f:
            f.write('Pre-processed text.')
            tmp = f.name
        try:
            out, _, code = _run_cli(['--preprocessed', tmp])
            self.assertEqual(code, 0)
            out_path = out.strip()
            if out_path and os.path.exists(out_path):
                os.unlink(out_path)
        finally:
            os.unlink(tmp)

    def test_invalid_voice_exits(self):
        _, err, code = _run_cli(['--voice', 'NonExistent', 'file.md'])
        self.assertEqual(code, 1)
        self.assertIn('unknown voice', err)
        self.assertIn('Valid voices', err)

    def test_invalid_model_exits(self):
        _, err, code = _run_cli(['--model', 'nonexistent', 'file.md'])
        self.assertEqual(code, 1)
        self.assertIn('unknown model', err)
        self.assertIn('Valid models', err)

    def test_undownloaded_model_exits(self):
        """--model with a valid but not-downloaded model should exit 1."""
        with mock.patch('mew.config.is_downloaded', return_value=False):
            _, err, code = _run_cli(['--model', 'fp16', 'file.md'])
        self.assertEqual(code, 1)
        self.assertIn('not downloaded', err)

    def test_voice_requires_argument(self):
        _, err, code = _run_cli(['--voice'])
        self.assertEqual(code, 1)
        self.assertIn('requires an argument', err)

    def test_model_requires_argument(self):
        _, err, code = _run_cli(['--model'])
        self.assertEqual(code, 1)
        self.assertIn('requires an argument', err)

    def test_voice_case_insensitive(self):
        """--voice should accept case-insensitive names."""
        with mock.patch('mew.config.is_downloaded', return_value=True):
            # Should not fail on validation (will fail on file not found)
            _, err, code = _run_cli(['--voice', 'adam', 'nonexistent.md'])
        # The error should be about the file, not the voice name
        self.assertIn('file not found', err)
        self.assertNotIn('unknown voice', err)

    def test_no_args_shows_synopsis(self):
        out, _, code = _run_cli([])
        self.assertEqual(code, 0)
        self.assertIn('Usage:', out)


# ── Flag interactions ────────────────────────────────────────────────────────

class TestFlagInteractions(unittest.TestCase):

    def test_i_and_p_mutually_exclusive(self):
        _, err, code = _run_cli(['-i', '-p', 'file.md'])
        self.assertEqual(code, 1)
        self.assertIn('mutually exclusive', err)

    def test_dry_run_and_preprocessed_mutually_exclusive(self):
        _, err, code = _run_cli(['-n', '-p', 'file.md'])
        self.assertEqual(code, 1)
        self.assertIn('mutually exclusive', err)

    def test_long_forms_mutually_exclusive(self):
        _, err, code = _run_cli(['--intermediate', '--preprocessed', 'file.md'])
        self.assertEqual(code, 1)
        self.assertIn('mutually exclusive', err)

    def test_dry_run_and_intermediate_compatible(self):
        """dry-run wins over intermediate (both preprocess, but dry-run doesn't write)."""
        with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
            f.write('Hello world.')
            tmp = f.name
        try:
            # -n -i: dry-run takes precedence (mode = whichever comes last,
            # but both are non-file-writing for the purpose of compatibility)
            # The spec says they're compatible (no error).
            _, err, code = _run_cli(['-n', '-i', tmp])
            self.assertNotIn('mutually exclusive', err)
        finally:
            os.unlink(tmp)


# ── Multi-file ───────────────────────────────────────────────────────────────

class TestMultiFile(unittest.TestCase):

    def test_multiple_files_accepted(self):
        """Multiple positional args should be accepted without error."""
        files = []
        try:
            for i in range(3):
                f = tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False)
                f.write(f'Content {i}.')
                f.close()
                files.append(f.name)

            out, _, code = _run_cli(files)
            self.assertEqual(code, 0)
            lines = [l for l in out.strip().splitlines() if l.strip()]
            self.assertEqual(len(lines), 3)
            for line in lines:
                out_path = line.strip()
                if os.path.exists(out_path):
                    os.unlink(out_path)
        finally:
            for f in files:
                if os.path.exists(f):
                    os.unlink(f)

    def test_missing_file_continues(self):
        """A missing file should print an error but continue to the next."""
        with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
            f.write('Content.')
            good_file = f.name
        try:
            out, err, code = _run_cli([good_file, 'does_not_exist.md'])
            self.assertEqual(code, 1)  # exit 1 because one file failed
            self.assertIn('file not found', err)
            # The good file should still have produced output
            lines = [l for l in out.strip().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)
            out_path = lines[0].strip()
            if os.path.exists(out_path):
                os.unlink(out_path)
        finally:
            os.unlink(good_file)

    def test_exit_code_1_on_any_failure(self):
        _, _, code = _run_cli(['nonexistent1.md', 'nonexistent2.md'])
        self.assertEqual(code, 1)

    def test_file_header_in_stderr_when_multi(self):
        """When processing multiple files, stderr should show [1/N] headers."""
        files = []
        try:
            for i in range(2):
                f = tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False)
                f.write(f'Content {i}.')
                f.close()
                files.append(f.name)

            _, err, code = _run_cli(files)
            self.assertIn('[1/2]', err)
            self.assertIn('[2/2]', err)
            # Clean up output files
            for line in _run_cli(files)[0].strip().splitlines():
                p = line.strip()
                if p and os.path.exists(p):
                    os.unlink(p)
        finally:
            for f in files:
                if os.path.exists(f):
                    os.unlink(f)

    def test_no_header_for_single_file(self):
        """Single file should not show [1/1] header."""
        with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
            f.write('Content.')
            tmp = f.name
        try:
            _, err, code = _run_cli([tmp])
            self.assertNotIn('[1/1]', err)
            out_path = _run_cli([tmp])[0].strip()
            if out_path and os.path.exists(out_path):
                os.unlink(out_path)
        finally:
            os.unlink(tmp)


# ── Dry-run ──────────────────────────────────────────────────────────────────

class TestDryRun(unittest.TestCase):

    def test_preprocessed_text_to_stdout(self):
        """--dry-run should output preprocessed text to stdout."""
        with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
            f.write('## Section\n\nHello world.\n')
            tmp = f.name
        try:
            out, _, code = _run_cli(['-n', tmp])
            self.assertEqual(code, 0)
            # Preprocessed text should appear on stdout
            self.assertIn('Hello world', out)
        finally:
            os.unlink(tmp)

    def test_no_files_written(self):
        """--dry-run should not create any output files."""
        with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
            f.write('Hello world.')
            tmp = f.name
        try:
            tmpdir = os.path.dirname(tmp)
            before = set(os.listdir(tmpdir))
            _run_cli(['-n', tmp])
            after = set(os.listdir(tmpdir))
            # Only the temp input file should exist, no new .mew.wav or .mew.md
            new_files = after - before
            mew_files = [f for f in new_files if '.mew.' in f]
            self.assertEqual(mew_files, [])
        finally:
            os.unlink(tmp)

    def test_dry_run_long_form(self):
        """--dry-run should work the same as -n."""
        with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False) as f:
            f.write('Hello.')
            tmp = f.name
        try:
            out_short, _, code_short = _run_cli(['-n', tmp])
            out_long, _, code_long = _run_cli(['--dry-run', tmp])
            self.assertEqual(code_short, code_long)
            self.assertEqual(out_short, out_long)
        finally:
            os.unlink(tmp)

    def test_multi_file_dry_run_headers(self):
        """Multi-file dry-run should show --- filename --- separators on stderr."""
        files = []
        try:
            for name in ['aaa', 'bbb']:
                f = tempfile.NamedTemporaryFile(
                    suffix='.md', prefix=name, mode='w', delete=False
                )
                f.write(f'{name} content.')
                f.close()
                files.append(f.name)

            # Force stderr to be a tty-like object that reports isatty=True
            _, err, code = _run_cli(['-n'] + files)
            self.assertEqual(code, 0)
            # The --- headers go to stderr
            self.assertIn('---', err)
        finally:
            for f in files:
                os.unlink(f)


if __name__ == '__main__':
    unittest.main()
