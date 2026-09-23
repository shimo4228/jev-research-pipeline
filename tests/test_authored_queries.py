"""Authored queries: query lines in the question file replace Qwen + Jev query_selection
for the questions that carry them, and `jrp queries check` trial-fetches them."""

from pathlib import Path

from jev_research_pipeline.model import Question
from jev_research_pipeline.pipeline.query_check import check_queries
from jev_research_pipeline.pipeline.run import authored_candidates
from jev_research_pipeline.questions import parse_queries, parse_questions, question_queries

from . import builders as b
from .conftest import ClientFactory
from .fakes import HF_SEARCH, fake_json

FILE = """<!-- jrp:questions:akc -->

## エージェントの記憶は何で決まるのか
- slug: agent-memory
- status: open
- hf: agent memory
- arxiv: agent memory benchmark
- github: agent memory
- web: agent memory evaluation

## クエリの無い問い
- slug: no-queries
- status: open

## 二つ目
- slug: second
- status: open
- arxiv: skill library
- arxiv: <|end|>
"""


def _questions() -> list[Question]:
    return parse_questions(FILE, line=b.LINE_IRI, opened_at=b.T0)


def test_query_lines_are_read_per_block_in_file_order():
    got = parse_queries(FILE)
    assert got["agent-memory"] == (
        ("hf_papers", "agent memory"),
        ("arxiv", "agent memory benchmark"),
        ("github", "agent memory"),
        ("web_search", "agent memory evaluation"),
    )
    assert "no-queries" not in got
    assert got["second"] == (("arxiv", "skill library"), ("arxiv", "<|end|>"))


def test_question_queries_are_keyed_by_question_id(tmp_path: Path):
    env = {"JRP_QUESTIONS_DIR": str(tmp_path)}
    (tmp_path / "akc.md").write_text(FILE, encoding="utf-8")
    questions = _questions()
    got = question_queries(env, "akc", questions)
    assert set(got) == {questions[0].id, questions[2].id}


def test_authored_candidates_filter_kinds_guard_text_and_note_what_was_used():
    questions = _questions()
    queries = {q.id: parse_queries(FILE)[q.slug] for q in questions if q.slug != "no-queries"}
    out, notes = authored_candidates(
        b.LINE_IRI, questions, queries, kinds=("arxiv", "hf_papers"), turn=0
    )
    assert {(c.adapter, c.text) for c in out} == {
        ("hf_papers", "agent memory"),
        ("arxiv", "agent memory benchmark"),
        ("arxiv", "skill library"),
    }
    assert notes == [
        "query: 問いファイルの 3 件を使用",
        "query: 検索語にならない行を skip (<|end|>)",
    ]


def test_each_adapter_starts_one_query_later_on_every_run_of_the_line():
    questions = _questions()
    queries = {q.id: parse_queries(FILE)[q.slug] for q in questions if q.slug != "no-queries"}

    def first_arxiv(turn: int) -> str:
        out, _ = authored_candidates(b.LINE_IRI, questions, queries, kinds=("arxiv",), turn=turn)
        return out[0].text

    # two arXiv queries: consecutive runs alternate, whatever the days between them
    assert [first_arxiv(t) for t in range(4)] == [
        "agent memory benchmark",
        "skill library",
        "agent memory benchmark",
        "skill library",
    ]


async def test_check_sends_each_query_once_and_prints_hits(tmp_path: Path, cassette: ClientFactory):
    first_two = FILE.split("## 二つ目")[0]
    text = first_two.replace("- arxiv: agent memory benchmark\n", "").replace(
        "- github: agent memory\n", ""
    )
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "akc.md").write_text(text, encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text('[tracks.akc]\nname = "AKC"\n', encoding="utf-8")
    env = {
        "JRP_QUESTIONS_DIR": str(tmp_path / "questions"),
        "JRP_DAILY_RESEARCH_CONFIG": str(config),
    }
    lines = await check_queries(env, "akc", http=cassette(fake_json(HF_SEARCH)), now=b.T0)
    joined = "\n".join(lines)
    assert "hf_papers: agent memory → 1 件" in joined
    assert "2026-09-20 " in joined  # newest titles carry their date
    assert "web_search: agent memory evaluation → TAVILY_API_KEY 未設定のため未送信" in joined
    assert "クエリ未設定" in joined  # the question without query lines
