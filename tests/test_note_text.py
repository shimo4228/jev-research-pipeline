"""The note's fixed text per language (note_text): ja / en / zh carry the same values, and
a note in any language is harvested exactly like a Japanese one."""

import re
import string
from pathlib import Path

import pytest

from jev_research_pipeline import note_text
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.note_text import LANGS, BadNoteLang, Lang, Msg, note_lang
from jev_research_pipeline.pipeline.runner import run_pipeline
from jev_research_pipeline.report import render_report, ticks
from jev_research_pipeline.report.markdown import QuestionSection, SourceEntry

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_world
from .test_e2e import env as env

CJK = re.compile(r"[぀-ヿ一-鿿]")
MESSAGES = {name: m for name, m in vars(note_text).items() if isinstance(m, Msg)}


def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}


@pytest.mark.parametrize("name", sorted(MESSAGES))
def test_every_language_carries_the_same_values(name: str):
    msg = MESSAGES[name]
    assert _fields(msg.ja) == _fields(msg.en) == _fields(msg.zh), name


def test_english_text_is_english():
    """A Japanese word left in the en column is a note that reads half in Japanese."""
    assert [n for n, m in MESSAGES.items() if CJK.search(m.en)] == []


def test_note_lang_defaults_to_japanese_and_refuses_anything_else():
    assert note_lang({}) == "ja"
    assert [note_lang({"JRP_NOTE_LANG": lang}) for lang in LANGS] == ["ja", "en", "zh"]
    with pytest.raises(BadNoteLang, match="JRP_NOTE_LANG"):
        note_lang({"JRP_NOTE_LANG": "fr"})


def _note(lang: Lang) -> str:
    section = QuestionSection(
        question_id=b.question().id,
        title=b.question().title,
        prose=None,
        evidence=(
            SourceEntry(source_id=b.source().id, title="t", gist="g", url="https://a.example"),
        ),
    )
    return render_report(
        report=b.report(),
        ctx=LineContext(line=b.line(), vocabulary=("agent memory",)),
        sections=[section],
        claims=[],
        review=[SourceEntry(source_id=b.source().id, title="r", gist="", url="https://r.example")],
        bridges=[],
        unjudged=[],
        operations=[],
        lang=lang,
    )


def test_the_machine_read_lines_do_not_change_with_the_language():
    """Only the three marks are read back; their lines are the same in every language, so a tick in an en or zh note is harvested like one in ja."""
    marks = {lang: re.findall(r"<!-- jrp:\S+ -->", _note(lang)) for lang in LANGS}
    assert marks["ja"] and marks["ja"] == marks["en"] == marks["zh"]
    for lang in LANGS:
        ticked = _note(lang).replace("- [ ] ", "- [x] ")
        assert ticks(ticked, "qday") == ticks(_note("ja").replace("- [ ] ", "- [x] "), "qday")


def test_an_english_note_has_english_headings():
    text = _note("en")
    for heading in ("### Evidence", "borderline sources"):
        assert heading in text
    assert "No prose generated (template). Evidence only." in text
    assert "- [ ] Worth reading <!-- jrp:qday:" in text


async def test_an_english_run_writes_no_japanese_of_its_own(
    cassette: ClientFactory,
    cassette_path: Path,
    env: dict[str, str],
):
    """End to end with JRP_NOTE_LANG=en: the operations section (the pipeline's own text)
    has no Japanese left in it, and the question-day keeps its mark."""
    env = {**env, "JRP_NOTE_LANG": "en"}
    (outcome,) = await run_pipeline(env, now=b.T0, http=cassette(fake_world()), pacing=False)
    text = Path(outcome.note).read_text(encoding="utf-8")
    ops = text.split("> [!info]- Operations\n", 1)[1]
    assert [line for line in ops.splitlines() if CJK.search(line)] == []
    assert any("web_search: skipped, key not set" in ln for ln in outcome.operations)
    assert "jrp:qday:" in text
    # the English prompt and the English rubric went on the wire
    wire = cassette_path.read_text(encoding="utf-8")
    assert "You explain the research that arrived today" in wire
    assert "English-reading practitioner" in wire
