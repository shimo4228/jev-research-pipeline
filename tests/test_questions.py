"""The author's question file: parsed every run, appended only on an adopted proposal."""

from pathlib import Path

import pytest

from jev_research_pipeline.model import Question
from jev_research_pipeline.questions import (
    NoQuestions,
    append_question,
    open_questions,
    parse_questions,
    questions_path,
    render_question,
    slugify,
)

from . import builders as b

FILE = """<!-- jrp:questions:akc -->

## エージェントの記憶は何で決まるのか
- slug: agent-memory
- version: 2
- status: open
- opened: 2026-09-01
- retire: 三ヶ月 evidence が増えなければ閉じる
- brief: 記憶機構の違いが下流の精度をどれだけ動かすか。
- method: RAG
- method: 長文 context
- evidence: 測定されたもの
- not: プロンプト技法一般
- canary: https://arxiv.org/abs/2609.01234

## 閉じた問い
- slug: closed-one
- status: answered
"""


def _env(tmp_path: Path) -> dict[str, str]:
    return {"JRP_QUESTIONS_DIR": str(tmp_path / "questions")}


def test_parse_reads_every_field_and_keeps_file_order():
    first, second = parse_questions(FILE, line=b.LINE_IRI, opened_at=b.T0)
    assert (first.slug, first.version, first.status) == ("agent-memory", 2, "open")
    assert first.title == "エージェントの記憶は何で決まるのか"
    assert first.method_constraints == ("RAG", "長文 context")
    assert first.evidence_constraints == ("測定されたもの",)
    assert first.negative_topics == ("プロンプト技法一般",)
    assert first.canary_papers == ("https://arxiv.org/abs/2609.01234",)
    assert first.opened_at.date().isoformat() == "2026-09-01"
    assert (second.slug, second.status) == ("closed-one", "answered")


def test_open_questions_skips_the_retired_ones(tmp_path: Path):
    env = _env(tmp_path)
    path = questions_path(env, "akc")
    path.parent.mkdir(parents=True)
    path.write_text(FILE, encoding="utf-8")
    questions = open_questions(env, "akc", line=b.LINE_IRI, now=b.T0)
    assert [q.slug for q in questions] == ["agent-memory"]


@pytest.mark.parametrize("text", ["", "<!-- jrp:questions:akc -->\n", "## q\n- status: dropped\n"])
def test_a_line_without_an_open_question_stops_the_run(tmp_path: Path, text: str):
    env = _env(tmp_path)
    path = questions_path(env, "akc")
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(NoQuestions, match="問い未設定"):
        open_questions(env, "akc", line=b.LINE_IRI, now=b.T0)


def test_a_missing_file_stops_the_run_too(tmp_path: Path):
    with pytest.raises(NoQuestions, match="問い未設定"):
        open_questions(_env(tmp_path), "akc", line=b.LINE_IRI, now=b.T0)


def test_render_round_trips_through_the_parser():
    written = b.question()
    (question,) = parse_questions(render_question(written), line=b.LINE_IRI, opened_at=b.T0)
    # The file carries a date, not a timestamp; everything else survives verbatim.
    skip = {"id", "evidence", "opened_at"}
    assert question.model_dump(exclude=skip) == written.model_dump(exclude=skip)
    assert question.opened_at.date() == written.opened_at.date()


def test_append_creates_the_file_and_is_idempotent(tmp_path: Path):
    env = _env(tmp_path)
    proposal = b.question()
    path = append_question(env, "akc", proposal)
    append_question(env, "akc", proposal)  # a second tick on the same proposal
    text = path.read_text(encoding="utf-8")
    assert text.count(f"- slug: {proposal.slug}") == 1
    assert parse_questions(text, line=b.LINE_IRI, opened_at=b.T0)[0].title == proposal.title


def test_append_keeps_what_the_author_wrote(tmp_path: Path):
    env = _env(tmp_path)
    path = questions_path(env, "akc")
    path.parent.mkdir(parents=True)
    path.write_text(FILE, encoding="utf-8")
    adopted = b.question().model_copy(
        update={"slug": "vantage-point", "id": Question.id_for(b.LINE_IRI, "vantage-point", 1)}
    )
    append_question(env, "akc", adopted)
    questions = parse_questions(path.read_text(encoding="utf-8"), line=b.LINE_IRI, opened_at=b.T0)
    assert [q.slug for q in questions] == ["agent-memory", "closed-one", "vantage-point"]


def test_a_japanese_title_still_gets_a_slug():
    slug = slugify("エージェントの記憶")
    assert slug and slug == slugify("エージェントの記憶")
    assert slug != slugify("別の問い")
    assert (
        Question.new(line=b.LINE_IRI, slug=slug, version=1, title="t", opened_at=b.T0).slug == slug
    )
