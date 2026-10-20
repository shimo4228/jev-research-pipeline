# Weekly review goldens

The note `jrp wbr` renders from the synthetic store of `tests/test_wbr.py` (no store data, no
third-party text), byte for byte:

- `2026-W45.ja.md` — the week 2026-W45 in Japanese, the author's note language.

The test compares the rendered note with the file. A change that means to change the note's
text or layout regenerates it, and the diff of the golden goes in the same commit:

    JRP_GOLDEN_UPDATE=1 uv run pytest tests/test_wbr.py -k golden

A red golden from a change that did not mean to touch the note is a regression of the
output, not a file to regenerate.
