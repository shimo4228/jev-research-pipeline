"""The author's question file: parsed every run, never written by a run."""

from pathlib import Path

import pytest

from jev_research_pipeline.model import Question
from jev_research_pipeline.questions import (
    NoQuestions,
    open_questions,
    parse_questions,
    questions_path,
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


def test_a_japanese_title_still_gets_a_slug():
    slug = slugify("エージェントの記憶")
    assert slug and slug == slugify("エージェントの記憶")
    assert slug != slugify("別の問い")
    assert (
        Question.new(line=b.LINE_IRI, slug=slug, version=1, title="t", opened_at=b.T0).slug == slug
    )


def test_the_stored_evidence_set_comes_back_into_the_run(tmp_path: Path):
    # Without this the whole "running answer" axis is inert: screening, novelty and
    # movement would all be judged against an empty evidence set, every day.
    env = _env(tmp_path)
    path = questions_path(env, "akc")
    path.parent.mkdir(parents=True)
    path.write_text(FILE, encoding="utf-8")
    stored = b.question().model_copy(
        update={
            "slug": "agent-memory",
            "version": 2,
            "id": Question.id_for(b.LINE_IRI, "agent-memory", 2),
            "evidence": (b.claim().id,),
        }
    )
    (question,) = open_questions(
        env,
        "akc",
        line=b.LINE_IRI,
        now=b.T0,
        stored={stored.id: stored},
        evidence_scope={b.claim().id},
    )
    assert question.evidence == (b.claim().id,)


def test_todays_own_claims_do_not_join_the_evidence_set_mid_run(tmp_path: Path):
    # The set is pinned to earlier days, so a same-day re-run asks Jev the same questions.
    env = _env(tmp_path)
    path = questions_path(env, "akc")
    path.parent.mkdir(parents=True)
    path.write_text(FILE, encoding="utf-8")
    stored = b.question().model_copy(
        update={
            "slug": "agent-memory",
            "version": 2,
            "id": Question.id_for(b.LINE_IRI, "agent-memory", 2),
            "evidence": (b.claim().id,),
        }
    )
    (question,) = open_questions(
        env, "akc", line=b.LINE_IRI, now=b.T0, stored={stored.id: stored}, evidence_scope=set()
    )
    assert question.evidence == ()
