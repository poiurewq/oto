#!/usr/bin/env python3
"""
test_preprocess.py — Unit tests for mew.preprocess

Run with:
    python3 -m pytest mew/test_preprocess.py
    python3 -m pytest mew/test_preprocess.py -v
    python3 -m pytest mew/test_preprocess.py::TestRanges
"""

import os
import tempfile
import unittest

from mew import preprocess as P


# ── _number_to_words ──────────────────────────────────────────────────────────

class TestNumberToWords(unittest.TestCase):

    def t(self, n, expected):
        self.assertEqual(P._number_to_words(n), expected, msg=f'_number_to_words({n})')

    # Basics
    def test_zero(self):           self.t(0,    'zero')
    def test_one(self):            self.t(1,    'one')
    def test_ten(self):            self.t(10,   'ten')
    def test_teens(self):          self.t(13,   'thirteen')
    def test_nineteen(self):       self.t(19,   'nineteen')
    def test_twenty(self):         self.t(20,   'twenty')
    def test_twenty_one(self):     self.t(21,   'twenty-one')
    def test_ninety_nine(self):    self.t(99,   'ninety-nine')

    # Hundreds
    def test_100(self):            self.t(100,  'one hundred')
    def test_500(self):            self.t(500,  'five hundred')
    def test_999(self):            self.t(999,  'nine hundred ninety-nine')
    def test_101(self):            self.t(101,  'one hundred one')

    # Thousands — exact multiples use "X thousand"
    def test_1000(self):           self.t(1000, 'one thousand')
    def test_2000(self):           self.t(2000, 'two thousand')
    def test_3000(self):           self.t(3000, 'three thousand')

    # Year-style 4-digit numbers
    def test_1900(self):           self.t(1900, 'nineteen hundred')
    def test_2100(self):           self.t(2100, 'twenty-one hundred')
    def test_1990(self):           self.t(1990, 'nineteen ninety')
    def test_2024(self):           self.t(2024, 'twenty twenty-four')
    def test_1066(self):           self.t(1066, 'ten sixty-six')
    def test_1800(self):           self.t(1800, 'eighteen hundred')

    # Negative
    def test_negative(self):       self.t(-5,   'negative five')
    def test_negative_year(self):  self.t(-42,  'negative forty-two')


# ── _expand_ranges ────────────────────────────────────────────────────────────

class TestExpandRanges(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._expand_ranges(text), expected, msg=repr(text))

    # Basic numeric ranges
    def test_small(self):          self.t('items 1-5',        'items one to five')
    def test_medium(self):         self.t('pages 10-20',      'pages ten to twenty')
    def test_hundreds(self):       self.t('100-200 cases',    'one hundred to two hundred cases')

    # Year ranges
    def test_year_range(self):     self.t('1990-2024',        'nineteen ninety to twenty twenty-four')
    def test_millennium(self):     self.t('2000-2010',        'two thousand to twenty ten')

    # Range embedded in sentence
    def test_sentence(self):
        self.t('stages 3-5 of training', 'stages three to five of training')

    # Things that must NOT be treated as ranges
    def test_word_hyphen(self):    self.t('well-being',        'well-being')       # no digits
    def test_no_digits(self):      self.t('self-care tips',    'self-care tips')
    def test_already_words(self):  self.t('one to five',       'one to five')

    # Multiple ranges in one line
    def test_multiple(self):
        self.t('between 1-3 and 7-9', 'between one to three and seven to nine')


# ── _deduplicate ──────────────────────────────────────────────────────────────

class TestDeduplicate(unittest.TestCase):

    def test_no_duplicates(self):
        lines = ['# Title\n', '\n', '## Section A\n', 'Content.\n']
        self.assertEqual(P._deduplicate(lines), lines)

    def test_duplicate_h2_removed(self):
        lines = [
            '# Title\n',
            '## Section A\n', 'Content A.\n',
            '## Section B\n', 'Content B.\n',
            '## Section A\n', 'Content A again.\n',  # duplicate — drop from here
            '## Section B\n', 'Content B again.\n',
        ]
        result = P._deduplicate(lines)
        self.assertEqual(result, [
            '# Title\n',
            '## Section A\n', 'Content A.\n',
            '## Section B\n', 'Content B.\n',
        ])

    def test_full_repeat(self):
        """Simulates the actual file: second half is a complete duplicate."""
        first_half = ['# Title\n', '## A\n', 'text\n', '## B\n', 'more\n']
        second_half = ['## A\n', 'text\n', '## B\n', 'more\n']
        result = P._deduplicate(first_half + second_half)
        self.assertEqual(result, first_half)

    def test_empty(self):
        self.assertEqual(P._deduplicate([]), [])


# ── _normalize_unicode ────────────────────────────────────────────────────────

class TestNormalizeUnicode(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._normalize_unicode(text), expected, msg=repr(text))

    def test_curly_apostrophe(self):   self.t('supervisee\u2019s', "supervisee's")
    def test_open_single_quote(self):  self.t('\u2018hello\u2019',  "'hello'")
    def test_curly_double_quotes(self):self.t('\u201chello\u201d',  '"hello"')
    def test_em_dash(self):            self.t('word\u2014word',     'word--word')
    def test_en_dash(self):            self.t('10\u201320',         '10 to 20')
    def test_ellipsis_char(self):      self.t('wait\u2026',         'wait...')
    def test_plain_text_unchanged(self): self.t('hello world',      'hello world')


# ── _strip_brackets ───────────────────────────────────────────────────────────

class TestStripBrackets(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._strip_brackets(text), expected, msg=repr(text))

    def test_single_citation(self):    self.t('text [1] more',     'text  more')
    def test_multi_citation(self):     self.t('text [1,2] end',    'text  end')
    def test_citation_with_spaces(self): self.t('[1, 2, 3]',       '')
    def test_bracket_text_kept(self):  self.t('[note] text',       'note text')
    def test_bracket_mid(self):        self.t('see [ACA] code',    'see ACA code')
    def test_no_brackets(self):        self.t('plain text',        'plain text')


# ── _expand_parens ────────────────────────────────────────────────────────────

class TestExpandParens(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._expand_parens(text), expected, msg=repr(text))

    def test_ex(self):
        self.t('cannot remain objective (ex. family members or friends).',
               'cannot remain objective, such as family members or friends.')

    def test_ie(self):
        self.t('the outcome (i.e. the result) matters.',
               'the outcome, that is the result, matters.')

    def test_eg(self):
        self.t('resources (e.g. books or workshops) help.',
               'resources, for example books or workshops, help.')

    def test_comma_before_period_cleaned(self):
        # Trailing comma before period must be removed.
        self.t('friends (ex. Bob).', 'friends, such as Bob.')

    def test_no_parens(self):
        self.t('plain sentence here.', 'plain sentence here.')


# ── _handle_slashes ───────────────────────────────────────────────────────────

class TestHandleSlashes(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._handle_slashes(text), expected, msg=repr(text))

    def test_and_or(self):             self.t('and/or this',         'and or this')
    def test_and_or_uppercase(self):   self.t('AND/OR',              'and or')
    def test_word_slash_word(self):    self.t('students/supervisees','students or supervisees')
    def test_educator_student(self):   self.t('educator/student',    'educator or student')
    def test_digit_slash_digit(self):  self.t('1/2 cup',             '1/2 cup')   # digits: not touched
    def test_no_slash(self):           self.t('plain text',          'plain text')
    def test_url_safe(self):
        # Slash in URL preceded by colon — lookbehind requires letter, colon fails.
        self.t('see http://example', 'see http://example')


# ── _expand_abbreviations ─────────────────────────────────────────────────────

class TestExpandAbbreviations(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._expand_abbreviations(text), expected, msg=repr(text))

    def test_eg_comma(self):     self.t('e.g., books',        'for example, books')
    def test_eg_no_comma(self):  self.t('e.g. books',         'for example books')
    def test_ie_comma(self):     self.t('i.e., this',         'that is, this')
    def test_ie_no_comma(self):  self.t('i.e. this',          'that is this')
    def test_ex_space(self):     self.t('ex. family',         'for example family')
    def test_ex_before_paren(self): self.t('ex.)',            'for example)')
    def test_etc(self):
        # `etc.` absorbs its own period — _needs_period() adds it back later in
        # the pipeline.  _expand_abbreviations alone produces no trailing period.
        self.t('and so on etc.',  'and so on and so on')
    def test_no_match(self):     self.t('regular text here.', 'regular text here.')

    def test_ex_not_in_word(self):
        # "example" must not be affected (preceded by a letter... wait "ex." in "example"
        # — the pattern requires NOT preceded by a letter, so "example" is safe.
        self.t('see the example here', 'see the example here')


# ── _strip_markdown ───────────────────────────────────────────────────────────

class TestStripMarkdown(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._strip_markdown(text), expected, msg=repr(text))

    def test_h1(self):             self.t('# Title',            'Title')
    def test_h2(self):             self.t('## Section',         'Section')
    def test_h3(self):             self.t('### Deep',           'Deep')
    def test_bold(self):           self.t('**bold text**',      'bold text')
    def test_italic_star(self):    self.t('*italic*',           'italic')
    def test_bold_italic(self):    self.t('***both***',         'both')
    def test_underline(self):      self.t('_under_',            'under')
    def test_double_underline(self): self.t('__strong__',       'strong')
    def test_plain_unchanged(self):self.t('plain text.',        'plain text.')
    def test_heading_with_text(self):
        self.t('## Monitoring Supervisees', 'Monitoring Supervisees')

    def test_no_heading_mid_line(self):
        # ## only stripped at start of line.
        self.t('text ## not a heading', 'text ## not a heading')


# ── _apply_substitutions ─────────────────────────────────────────────────────

class TestApplySubstitutions(unittest.TestCase):

    def test_literal_replace_all(self):
        subs = [{"find": "vs.", "replace": "versus", "regex": False, "first_only": False}]
        result = P._apply_substitutions("A vs. B vs. C", subs, set())
        self.assertEqual(result, "A versus B versus C")

    def test_literal_first_only(self):
        subs = [{"find": "ACA", "replace": "ACA, the American Counseling Association,", "regex": False, "first_only": True}]
        seen = set()
        result = P._apply_substitutions("The ACA Code. The ACA again.", subs, seen)
        self.assertEqual(result.count("American Counseling Association"), 1)
        self.assertIn("ACA", seen)

    def test_first_only_seen_persists_across_lines(self):
        subs = [{"find": "ACA", "replace": "expanded", "regex": False, "first_only": True}]
        seen = set()
        P._apply_substitutions("ACA here", subs, seen)
        result = P._apply_substitutions("ACA again", subs, seen)
        self.assertEqual(result, "ACA again")

    def test_regex_replace(self):
        subs = [{"find": r"\bCEO\b", "replace": "C.E.O.", "regex": True, "first_only": False}]
        result = P._apply_substitutions("The CEO spoke to other CEO leaders", subs, set())
        self.assertEqual(result, "The C.E.O. spoke to other C.E.O. leaders")

    def test_regex_first_only(self):
        subs = [{"find": r"\bWHO\b", "replace": "WHO, the World Health Organization,", "regex": True, "first_only": True}]
        seen = set()
        result = P._apply_substitutions("The WHO released. WHO guidelines.", subs, seen)
        self.assertEqual(result.count("World Health Organization"), 1)
        self.assertIn(r"\bWHO\b", seen)

    def test_regex_backreference(self):
        subs = [{"find": r"\b(\d+)mg\b", "replace": r"\1 milligrams", "regex": True, "first_only": False}]
        result = P._apply_substitutions("Take 500mg daily", subs, set())
        self.assertEqual(result, "Take 500 milligrams daily")

    def test_ordering_matters(self):
        """Earlier entries take precedence over later ones."""
        subs = [
            {"find": "w/o", "replace": "without", "regex": False, "first_only": False},
            {"find": "w/", "replace": "with", "regex": False, "first_only": False},
        ]
        result = P._apply_substitutions("go w/o it and w/ friends", subs, set())
        self.assertIn("without", result)
        self.assertIn("with", result)

    def test_empty_subs_no_change(self):
        result = P._apply_substitutions("unchanged text", [], set())
        self.assertEqual(result, "unchanged text")

    def test_invalid_regex_skipped(self):
        subs = [{"find": r"[invalid", "replace": "x", "regex": True, "first_only": False}]
        result = P._apply_substitutions("some text", subs, set())
        self.assertEqual(result, "some text")


# ── _add_intro_commas ─────────────────────────────────────────────────────────

class TestAddIntroCommas(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._add_intro_commas(text), expected, msg=repr(text))

    def test_when_they(self):
        self.t('When students act as supervisors they must understand.',
               'When students act as supervisors, they must understand.')

    def test_during_counselors(self):
        self.t('During program orientation counselors should include the values.',
               'During program orientation, counselors should include the values.')

    def test_already_has_comma_early(self):
        # Comma within first 50 chars → leave alone.
        self.t('Before offering supervision, counselors must be prepared.',
               'Before offering supervision, counselors must be prepared.')

    def test_already_has_comma_before_subject(self):
        # Comma exists before the detected subject → leave alone.
        self.t('If termination of the relationship is warranted, the supervisor must act.',
               'If termination of the relationship is warranted, the supervisor must act.')

    def test_no_intro_word(self):
        self.t('Supervisors must monitor services.', 'Supervisors must monitor services.')

    def test_short_intro_no_subject(self):
        # Starts with intro word but subject not in our list → leave alone.
        self.t('Since then, nothing changed.', 'Since then, nothing changed.')


# ── _add_breathing_commas ─────────────────────────────────────────────────────

class TestAddBreathingCommas(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._add_breathing_commas(text), expected, msg=repr(text))

    def test_long_sentence_and(self):
        line = 'Counselors should always be aware of the ethical standards that govern their professional practice and they must act in accordance with those guidelines at all times.\n'
        result = P._add_breathing_commas(line)
        self.assertIn(', and', result)

    def test_long_sentence_but(self):
        line = 'The supervisor reviewed all of the documentation from the recent sessions very carefully but the trainee had not completed the required forms.\n'
        result = P._add_breathing_commas(line)
        self.assertIn(', but', result)

    def test_short_sentence_unchanged(self):
        self.t('Students and supervisors must cooperate.\n',
               'Students and supervisors must cooperate.\n')

    def test_already_has_comma(self):
        line = 'Counselors should always be aware of the standards, and they must act accordingly at all times during supervision.\n'
        self.t(line, line)  # comma already present, no change

    def test_no_conjunction(self):
        line = 'Counselors should always be aware of the ethical standards that govern their practice in all professional settings.\n'
        self.t(line, line)


# ── _wrap_in_quotes ──────────────────────────────────────────────────────────

class TestWrapInQuotes(unittest.TestCase):

    def t(self, text, expected):
        self.assertEqual(P._wrap_in_quotes(text), expected, msg=repr(text))

    def test_basic_sentence(self):
        self.t('Some content here.\n', '"Some content here."\n')

    def test_blank_line_skipped(self):
        self.t('\n', '\n')
        self.t('', '')

    def test_section_break_skipped(self):
        self.t('...\n', '...\n')

    def test_already_has_quotes(self):
        self.t('He said "hello" to them.\n', 'He said "hello" to them.\n')

    def test_strips_surrounding_whitespace(self):
        self.t('  indented text.  \n', '"indented text."\n')


# ── _needs_period ─────────────────────────────────────────────────────────────

class TestNeedsPeriod(unittest.TestCase):

    def yes(self, line): self.assertTrue(P._needs_period(line),  msg=repr(line))
    def no(self, line):  self.assertFalse(P._needs_period(line), msg=repr(line))

    def test_bare_text(self):         self.yes('Some text')
    def test_bare_text_newline(self): self.yes('Some text\n')
    def test_already_period(self):    self.no('Some text.')
    def test_question_mark(self):     self.no('Really?')
    def test_exclamation(self):       self.no('Stop!')
    def test_colon(self):             self.no('Potential Problems:')
    def test_empty_string(self):      self.no('')
    def test_blank_line(self):        self.no('\n')
    def test_horizontal_rule(self):   self.no('---')
    def test_hr_stars(self):          self.no('***')
    def test_ellipsis(self):          self.no('wait...')
    def test_number_item(self):       self.yes('Number one: Failing to monitor')


# ── Integration: process() ────────────────────────────────────────────────────

class TestProcess(unittest.TestCase):

    def _run(self, content: str) -> str:
        """Write content to a temp .md file, run process(), return output."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md',
                                        delete=False, encoding='utf-8') as f:
            f.write(content)
            inp = f.name
        try:
            out_path = P.process(inp)
            with open(out_path, encoding='utf-8') as f:
                return f.read()
        finally:
            os.unlink(inp)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_header_stripped_and_period_added(self):
        out = self._run('## Monitoring Supervisees\n')
        self.assertIn('"Monitoring Supervisees."', out)
        self.assertNotIn('##', out)

    def test_section_break_inserted(self):
        out = self._run('## Section A\ntext\n## Section B\ntext\n')
        self.assertIn('...', out)

    def test_bullet_numbered(self):
        out = self._run('## S\nPotential Problems:\n\n- Item one\n- Item two\n')
        self.assertIn('"Number one: Item one."', out)
        self.assertIn('"Number two: Item two."', out)

    def test_numbering_resets_per_label(self):
        out = self._run(
            '## S\n'
            'Potential Problems:\n\n- A\n- B\n\n'
            'Recommendations and Resolutions:\n\n- C\n- D\n'
        )
        lines = out.splitlines()
        numbered = [l for l in lines if 'Number' in l]
        self.assertEqual(numbered[0], '"Number one: A."')
        self.assertEqual(numbered[2], '"Number one: C."')

    def test_deduplication(self):
        block = '## Section\nsome content\n'
        out = self._run(block + block)
        self.assertEqual(out.count('"Section."'), 1)

    def test_substitutions_applied_when_file_exists(self):
        """Substitutions from file are applied during process()."""
        import json
        subs_file = P.SUBSTITUTIONS_FILE
        had_file = subs_file.exists()
        old_content = subs_file.read_text() if had_file else None
        try:
            subs_file.parent.mkdir(parents=True, exist_ok=True)
            subs_file.write_text(json.dumps([
                {"find": r"\bACA\b", "replace": "ACA, the American Counseling Association,",
                 "regex": True, "first_only": True},
            ]))
            out = self._run('## S\nThe ACA Code. The ACA again.\n')
            self.assertEqual(
                out.count('American Counseling Association'), 1,
                'ACA should be expanded exactly once via substitutions',
            )
        finally:
            if old_content is not None:
                subs_file.write_text(old_content)
            elif subs_file.exists():
                subs_file.unlink()

    def test_slash_converted(self):
        out = self._run('## S\nstudents/supervisees must comply.\n')
        self.assertIn('students or supervisees', out)

    def test_unicode_em_dash(self):
        out = self._run('## S\nresult\u2014surprising.\n')
        self.assertIn('"result--surprising."', out)

    def test_range_expanded(self):
        out = self._run('## S\ncomplete stages 1-3 first.\n')
        self.assertIn('one to three', out)

    def test_lines_wrapped_in_quotes(self):
        out = self._run('## S\nSome content here.\n')
        self.assertIn('"Some content here."', out)

    def test_section_break_not_quoted(self):
        out = self._run('## A\ntext\n## B\ntext\n')
        # The "..." section break should NOT be wrapped in quotes
        lines = out.splitlines()
        ellipsis_lines = [l for l in lines if l.strip() == '...']
        self.assertTrue(len(ellipsis_lines) > 0, 'section break should remain bare ...')

    def test_output_filename(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md',
                                        delete=False, encoding='utf-8') as f:
            f.write('# Title\n')
            inp = f.name
        try:
            out = P.process(inp)
            self.assertTrue(out.endswith('-processed.md'))
        finally:
            os.unlink(inp)
            if os.path.exists(out):
                os.unlink(out)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    unittest.main(verbosity=2)
