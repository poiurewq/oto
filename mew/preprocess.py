"""
preprocess.py — Prepares a Markdown file for KittenTTS ONNS.

Transformations applied (in pipeline order):
  5.  Deduplicate repeated sections (keeps first occurrence of each ## header)
  9.  Normalize Unicode punctuation:
        curly quotes → straight, en-dash → " to ", em-dash → "--" (KittenTTS
        dramatic pause), ellipsis char → "..."
 []   Strip bracket expressions: [1], [1,2] citation markers removed;
        [text] brackets removed (content kept) — KittenTTS stumbles on []
 10.  Expand parenthetical abbreviations:
        (ex. X) → ", such as X"   (i.e. X) → ", that is X"   (e.g. X) → ", for example X"
 RG.  Expand numeric ranges: 10-20 → "ten to twenty", 1990-2024 → "nineteen ninety to..."
  6.  Replace slashes with " or ": and/or, word/word
  1.  Expand inline abbreviations: e.g., i.e., ex., etc.
  2.  Strip Markdown formatting symbols (#, **, *, _) — KittenTTS stumbles on # and *
  4.  Expand known acronyms on first use (ACA → ACA, the American Counseling Association,)
 IC.  Add commas after introductory subordinate clauses missing one
        ("When students act as supervisors they must" → "…supervisors, they must")
  3.  Remove bullet dashes (-)
  7.  Number bullet items within labeled sections (Number one: …, Number two: …)
  8.  Insert section breaks around headings using double blank lines + "..."
        Extra blank line after label lines ("Potential Problems:") for breathing room
  +.  Append period to any line still missing terminal punctuation

KittenTTS punctuation reference (from engine docs):
  ,    comma    — breathing pause, most important for natural flow
  ...  ellipsis — soft hesitation / trailing-off pause
  .    period   — full stop, falling pitch
  --   dash     — sharp dramatic break
  ?    question — forces rising pitch at end of phrase
"""

import re
import sys
import os

# ── Number → words (used by expand_ranges) ────────────────────────────────────

_N_ONES = [
    '', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
    'seventeen', 'eighteen', 'nineteen',
]
_N_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']


def _number_to_words(n: int) -> str:
    """Convert a non-negative integer to English words (sufficient for ranges)."""
    if n < 0:
        return 'negative ' + _number_to_words(-n)
    if n == 0:
        return 'zero'
    if n < 20:
        return _N_ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _N_TENS[tens] + ('-' + _N_ONES[ones] if ones else '')
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        tail = (' ' + _number_to_words(rest)) if rest else ''
        return _N_ONES[hundreds] + ' hundred' + tail
    # 1000–9999: years like 1990 read as "nineteen ninety", others as "N thousand M"
    if 1000 <= n <= 9999:
        if n % 1000 == 0:
            return _number_to_words(n // 1000) + ' thousand'
        high, low = divmod(n, 100)
        if low == 0:
            return _number_to_words(high) + ' hundred'
        return _number_to_words(high) + ' ' + _number_to_words(low)
    thousands, rest = divmod(n, 1000)
    tail = (' ' + _number_to_words(rest)) if rest else ''
    return _number_to_words(thousands) + ' thousand' + tail


# DT. Date/time patterns — must be matched before range expansion.
_MONTHS = [
    '', 'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
]

_DAY_SUFFIXES = {1: 'st', 2: 'nd', 3: 'rd', 21: 'st', 22: 'nd', 23: 'rd', 31: 'st'}


def _day_ordinal(d: int) -> str:
    return f'{d}{_DAY_SUFFIXES.get(d, "th")}'


def _time_to_words(h: int, m: int) -> str:
    if h == 0 and m == 0:
        return 'midnight'
    if h == 12 and m == 0:
        return 'noon'
    period = 'AM' if h < 12 else 'PM'
    display_h = h % 12 or 12
    if m == 0:
        return f'{display_h} {period}'
    return f'{display_h}:{m:02d} {period}'


# YYYY-MM-DD or YYYY.MM.DD, optional separator + HH:MM
_RE_DATETIME = re.compile(
    r'(?<!\w)'
    r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})'   # date: YYYY-MM-DD or YYYY.MM.DD
    r'(?:'
    r'[\s\-T](\d{1,2}):(\d{2})'               # optional time: HH:MM
    r')?'
    r'(?!\w)'
)


def _expand_datetimes(line: str) -> str:
    """DT. Convert date/timestamp patterns to natural speech."""
    def _repl(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)  # not a valid date, leave as-is
        parts = [f'{_MONTHS[mo]} {_day_ordinal(d)}, {y}']
        if m.group(4) is not None:
            h, mi = int(m.group(4)), int(m.group(5))
            if 0 <= h <= 23 and 0 <= mi <= 59:
                parts.append(f'at {_time_to_words(h, mi)}')
        return ' '.join(parts)
    return _RE_DATETIME.sub(_repl, line)


# RG. Numeric range pattern: digits-digits not surrounded by other word chars.
_RE_RANGE = re.compile(r'(?<!\w)(\d+)-(\d+)(?!\w)')

# ── Configuration ──────────────────────────────────────────────────────────────

# 4. Acronyms to expand on first use only.
ACRONYMS: dict[str, str] = {
    'ACA': 'ACA, the American Counseling Association,',
}

# 1. Abbreviation patterns (order matters: longer/more-specific first).
ABBREVIATIONS: list[tuple] = [
    (re.compile(r'\be\.g\.,\s*'),                'for example, '),
    (re.compile(r'\be\.g\.'),                    'for example'),
    (re.compile(r'\bi\.e\.,\s*'),                'that is, '),
    (re.compile(r'\bi\.e\.'),                    'that is'),
    # "ex." used as abbreviation for "example" (not preceded by a letter)
    (re.compile(r'(?<![A-Za-z])ex\.\s+'),        'for example '),
    (re.compile(r'(?<![A-Za-z])ex\.(?=[,);])'),  'for example'),
    (re.compile(r'\betc\.'),                     'and so on'),
]

# IC. Introductory conjunctions/prepositions that begin subordinate clauses.
_INTRO_RE = re.compile(
    r'^(If|When|Before|After|Because|Although|While|During|Since|Once)\s',
    re.IGNORECASE,
)
# Main-clause subjects we look for to place the comma before.
_SUBJECT_RE = re.compile(
    r'(?<=\s)(they|he|she|it|we'
    r'|counselors?|supervisors?|students?|trainees?|educators?|clients?'
    r'|the\s+(?:supervisor|counselor|student|trainee|educator|client))\b',
    re.IGNORECASE,
)

# Spoken ordinals for numbered list items (supports up to 20).
_ORDINALS = [
    'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
    'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
    'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty',
]

# Label lines that introduce a numbered sub-list.
_LABEL_RE = re.compile(
    r'^(Potential Problems|Recommendations and Resolutions)\s*:',
    re.IGNORECASE,
)

# Characters that already signal a sentence boundary to a TTS engine.
# ':' is included so label lines ("Potential Problems:") are left alone.
_TERMINAL = frozenset('.?!:')


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ordinal(n: int) -> str:
    return _ORDINALS[n - 1] if 1 <= n <= len(_ORDINALS) else str(n)


def _needs_period(line: str) -> bool:
    s = line.rstrip()
    if not s:
        return False
    if re.fullmatch(r'[-*_]{3,}', s):   # horizontal rules
        return False
    return s[-1] not in _TERMINAL


# ── Transformation functions ───────────────────────────────────────────────────

def _deduplicate(lines: list[str]) -> list[str]:
    """5. Drop any section whose heading (# or ##) has already appeared."""
    seen: set[str] = set()
    result: list[str] = []
    skip = False
    for line in lines:
        s = line.strip()
        if s.startswith('#'):
            if s in seen:
                skip = True
                continue
            seen.add(s)
            skip = False
        if not skip:
            result.append(line)
    return result


def _normalize_unicode(line: str) -> str:
    """9. Replace typographic characters with KittenTTS-friendly equivalents."""
    return (line
        .replace('\u2019', "'").replace('\u2018', "'")   # curly apostrophes
        .replace('\u201c', '"').replace('\u201d', '"')   # curly double quotes
        .replace('\u2014', '--')        # em dash  → dramatic KittenTTS pause
        .replace('\u2013', ' to ')      # en dash  → "to" (ranges)
        .replace('\u2026', '...')       # ellipsis char → three dots
    )


def _strip_brackets(line: str) -> str:
    """Remove [] bracket expressions — KittenTTS stumbles on them."""
    line = re.sub(r'\[\d+(?:,\s*\d+)*\]', '', line)   # [1], [1,2] citations
    line = re.sub(r'\[([^\]]*)\]', r'\1', line)        # [text] → text
    return line


def _expand_parens(line: str) -> str:
    """10. Convert parenthetical abbreviations into readable inline clauses."""
    line = re.sub(r'\s*\(\s*ex\.\s*([^)]+)\)',    r', such as \1,', line)
    line = re.sub(r'\s*\(\s*i\.e\.\s*([^)]+)\)',  r', that is \1,', line)
    line = re.sub(r'\s*\(\s*e\.g\.\s*([^)]+)\)',  r', for example \1,', line)
    line = re.sub(r',\s*([.!?])', r'\1', line)
    return line


def _expand_ranges(line: str) -> str:
    """RG. Expand numeric ranges: 10-20 → 'ten to twenty'."""
    return _RE_RANGE.sub(
        lambda m: f'{_number_to_words(int(m.group(1)))} to {_number_to_words(int(m.group(2)))}',
        line,
    )


def _handle_slashes(line: str) -> str:
    """6. Replace slash-separated alternatives with ' or '."""
    line = re.sub(r'\band/or\b', 'and or', line, flags=re.IGNORECASE)
    line = re.sub(r'(?<=[A-Za-z])/(?=[A-Za-z])', ' or ', line)
    return line


def _expand_abbreviations(line: str) -> str:
    """1. Expand common abbreviations to their spoken form."""
    for pattern, replacement in ABBREVIATIONS:
        line = pattern.sub(replacement, line)
    return line


def _strip_markdown(line: str) -> str:
    """2. Remove Markdown syntax that KittenTTS would read aloud literally."""
    line = re.sub(r'^#{1,6}\s+', '', line)               # heading hashes
    line = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', line)  # bold / italic *
    line = re.sub(r'_{1,3}(.+?)_{1,3}', r'\1', line)    # bold / italic _
    return line


def _expand_acronyms(line: str, seen: set) -> str:
    """4. Expand each known acronym on its very first appearance."""
    for acronym, expansion in ACRONYMS.items():
        if re.search(rf'\b{re.escape(acronym)}\b', line) and acronym not in seen:
            line = re.sub(rf'\b{re.escape(acronym)}\b', expansion, line, count=1)
            seen.add(acronym)
    return line


def _add_intro_commas(line: str) -> str:
    """IC. Add a comma after introductory subordinate clauses that are missing one."""
    if not _INTRO_RE.match(line):
        return line
    first_comma = line.find(',')
    if 0 < first_comma < 50:
        return line
    m = _SUBJECT_RE.search(line, 25)
    if m:
        pos = m.start()
        if ',' not in line[:pos]:
            return line[:pos].rstrip() + ', ' + line[pos:]
    return line


# ── Main processing loop ───────────────────────────────────────────────────────

def process(input_path: str, output_path: 'str | None' = None) -> str:
    """Preprocess *input_path* and write the result to *output_path*.

    If *output_path* is ``None``, defaults to ``<base>-processed<ext>``.
    Returns the path of the output file.
    """
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = base + '-processed' + (ext or '.md')

    with open(input_path, 'r', encoding='utf-8') as fh:
        lines = fh.readlines()

    lines = _deduplicate(lines)

    seen_acronyms: set = set()
    in_list_section = False
    item_count = 0
    out: list[str] = []

    for raw_line in lines:
        s = raw_line.strip()
        is_blank   = not s
        is_heading = bool(re.match(r'^#{1,6}\s', s))
        is_label   = bool(_LABEL_RE.match(s))
        is_bullet  = s.startswith('- ')

        if is_label:
            in_list_section = True
            item_count = 0
        elif is_heading:
            in_list_section = False
            item_count = 0

        if is_heading and out:
            out.append('\n')
            out.append('...\n')
            out.append('\n')

        line = _normalize_unicode(raw_line)
        line = _strip_brackets(line)
        line = _expand_parens(line)
        line = _expand_datetimes(line)
        line = _expand_ranges(line)
        line = _handle_slashes(line)
        line = _expand_abbreviations(line)
        line = _strip_markdown(line)
        line = _expand_acronyms(line, seen_acronyms)
        line = _add_intro_commas(line)

        if is_bullet:
            content = re.sub(r'^-\s+', '', line.rstrip())
            if in_list_section:
                item_count += 1
                line = f'Number {_ordinal(item_count)}: {content}\n'
            else:
                line = content + '\n'

        if _needs_period(line):
            line = line.rstrip() + '.\n'

        out.append(line)

        if is_heading or is_label:
            out.append('\n')

    with open(output_path, 'w', encoding='utf-8') as fh:
        fh.writelines(out)

    return output_path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f'Usage: {sys.argv[0]} input_file', file=sys.stderr)
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f'Error: not found: {path}', file=sys.stderr)
        sys.exit(1)
    out = process(path)
    print(f'Written: {out}')
