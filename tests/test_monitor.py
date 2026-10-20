"""The weekly review's monitoring judge (pipeline.monitor): Claude on the Claude API through
httpx2.MockTransport, never the real API. The week is tests/test_wbr.py's scenario: three
sections with prose (akc / agent-memory and akc / memory-eval on 11-03, edge / edge-q on
11-04) and two O1 papers (c1 and d1, first cited on 11-03)."""

import asyncio
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic_ai.models.anthropic import AnthropicModel

from jev_research_pipeline.generation import ProseAuth, Writer
from jev_research_pipeline.model import Question
from jev_research_pipeline.note_text import Lang
from jev_research_pipeline.pipeline import monitor
from jev_research_pipeline.pipeline.metrics import append_row, lines
from jev_research_pipeline.pipeline.monitor import (
    LEDGER_FILE,
    MODEL,
    Call,
    MonitorResult,
    Paper,
    Sample,
    Section,
    Tally,
    draw,
    monitor_judge,
    read_rubric,
    week_spent,
)
from jev_research_pipeline.pipeline.prose_bench import BenchCase, BenchClaim
from jev_research_pipeline.pipeline.prose_eval import JUDGE_INSTRUCTIONS, sha
from jev_research_pipeline.pipeline.wbr import (
    WEEKLY_FILE,
    monitor_sample,
    render,
    weekly_review,
    write_weekly_review,
)
from jev_research_pipeline.reduction.used import keys_of_text

from .conftest import Handler
from .test_wbr import AKC, CJK, NOW, WEEK, inputs, scenario_on_disk

KEY = {"ANTHROPIC_API_KEY": "sk-ant-test"}
RUBRIC = read_rubric("ja")
USD = (1000 * 4.0 + 100 * 20.0) / 1_000_000
"""One synthetic reply's price: 1,000 input and 100 output tokens at Opus 5.5's API rates."""
SPENT_WEEK = "2026-W46"
"""NOW is Monday 2026-11-09: the review of W45 spends in W46."""


def _body(request: httpx2.Request) -> dict[str, Any]:
    return json.loads(request.content)


def _kind(body: Mapping[str, Any]) -> str:
    schema = body["output_config"]["format"]["schema"]
    return "fidelity" if "verdict" in schema["properties"] else "precision"


def _prompt(body: Mapping[str, Any]) -> str:
    return body["messages"][0]["content"][0]["text"]


def _reply(body: Mapping[str, Any], answer: Mapping[str, object]) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_synthetic",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [{"type": "text", "text": json.dumps(answer, ensure_ascii=False)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 100},
        },
    )


def _answer(body: Mapping[str, Any]) -> dict[str, object]:
    """memory-eval's prose fails, the others pass; c1's claim moves its question in part,
    d1's does not."""
    prompt = _prompt(body)
    if _kind(body) == "fidelity":
        verdict = "fail" if "評価の指標 [1]。" in prompt else "pass"
        return {"verdict": verdict, "evidence": [{"question": "Q1 数値", "answer": "Yes"}]}
    return {"answer": "partial" if "<paper>\nc1\n</paper>" in prompt else "no", "reason": "r"}


def _answered(body: dict[str, Any]) -> httpx2.Response:
    return _reply(body, _answer(body))


class Api:
    """The Claude API's stand-in: every request, and the reply `respond` gives it."""

    def __init__(self, respond: Callable[[dict[str, Any]], httpx2.Response] = _answered):
        self.sent: list[httpx2.Request] = []
        self._respond = respond

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(request)
        return self._respond(_body(request))


def _error(status: int, message: str) -> Callable[[dict[str, Any]], httpx2.Response]:
    def respond(_: dict[str, Any]) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "error", "message": message}}
        )

    return respond


SAMPLE = monitor_sample(inputs(), WEEK, "ja")


async def _judge(
    tmp_path: Path,
    handler: Handler,
    *,
    env: Mapping[str, str] = KEY,
    sample: Sample = SAMPLE,
    rubric: str | None = RUBRIC,
    concurrency: int = monitor.CONCURRENCY,
    deadline_s: float = monitor.DEADLINE_S,
) -> MonitorResult:
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        return await monitor_judge(
            sample,
            env,
            tmp_path / LEDGER_FILE,
            http=http,
            now=NOW,
            rubric=rubric,
            concurrency=concurrency,
            deadline_s=deadline_s,
        )


def _ledger(tmp_path: Path) -> list[Call]:
    path = tmp_path / LEDGER_FILE
    return [Call.model_validate_json(raw) for raw in path.read_text(encoding="utf-8").splitlines()]


REVIEW = weekly_review(inputs(), WEEK)


def _shown(result: MonitorResult, lang: Lang = "ja") -> list[str]:
    """Section 1's monitor lines of the scenario's note."""
    text = render(replace(REVIEW, monitor=result), lang)
    return [line for line in text.splitlines() if line.startswith("- ") and "judge" in line]


# ------------------------------------------------------------------------------ the sample


def test_the_sample_is_the_weeks_sections_with_prose_and_its_o1_papers():
    assert sorted(s.label for s in SAMPLE.sections) == [
        "akc / agent-memory",
        "akc / memory-eval",
        "edge / edge-q",
    ]
    memory = next(s for s in SAMPLE.sections if s.label == "akc / agent-memory")
    assert memory.case.baseline == "新しい結果 [2]。"
    assert [s.title for s in memory.case.sources] == ["a1", "c1"]  # the section's own [n] order
    papers = {p.key: p for p in SAMPLE.papers}
    assert sorted(papers) == ["arxiv:2611.00001", "arxiv:2611.00002"]  # edge's e1 is a1's paper
    c1 = papers["arxiv:2611.00001"]
    assert (c1.line, c1.question.slug, c1.title) == ("akc", "agent-memory", "c1")
    assert c1.claim.startswith("Agents remember")
    assert papers["arxiv:2611.00002"].question.slug == "memory-eval"


def _case(i: int) -> BenchCase:
    return BenchCase(
        id=f"{i:012x}",
        split="dev",
        line_slug="akc",
        line_name="AKC",
        vocabulary=("agent memory",),
        question_title="Q",
        question_brief="",
        run_date=date(2026, 11, 3),
        claims=(BenchClaim(text="c", source=None),),
        known=(),
        sources=(),
        baseline=f"prose {i} [1]。",
    )


def test_the_sample_is_drawn_from_the_weeks_label_whatever_the_order():
    question = AKC["agent-memory"]
    sections = [Section(f"log-{i:02d}", "akc", "agent-memory", _case(i)) for i in range(20)]
    papers = [Paper(f"arxiv:2611.{i:05d}", "akc", question, "c", "t") for i in range(30)]
    first = draw("2026-W45", "ja", sections, papers)
    again = draw("2026-W45", "ja", list(reversed(sections)), papers[::-1])
    assert first == again
    assert (len(first.sections), len(first.papers)) == (monitor.FIDELITY_N, monitor.PRECISION_N)
    assert len({s.log for s in first.sections}) == monitor.FIDELITY_N
    other = draw("2026-W46", "ja", sections, papers)
    assert [s.log for s in other.sections] != [s.log for s in first.sections]
    few = draw("2026-W45", "ja", sections[:3], papers[:2])
    assert sorted(s.log for s in few.sections) == ["log-00", "log-01", "log-02"]
    assert len(few.papers) == 2


def test_the_rubric_is_read_in_each_note_language(monkeypatch: pytest.MonkeyPatch):
    for lang in ("ja", "en", "zh"):
        rubric = read_rubric(lang)
        assert rubric is not None and "Q6" in rubric
    monkeypatch.setattr(monitor, "RUBRICS", {"ja": Path("/nonexistent/prose-rubric.md")})
    assert read_rubric("ja") is None


# ---------------------------------------------------------------------------- no key, no call


async def test_without_a_key_nothing_is_called_or_written(tmp_path: Path):
    api = Api()
    result = await _judge(tmp_path, api, env={})
    assert api.sent == []
    assert not (tmp_path / LEDGER_FILE).exists()
    assert result.fidelity == Tally(asked=3, stop="no-key")
    assert result.precision == Tally(asked=2, stop="no-key")
    assert _shown(result) == [
        "- OUT 精度標本 (監視 judge、O1 の論文から最大 12 本、claim は問いを前に進めるか):"
        " 未測定 (key なし)",
        "- W 忠実さの標本 (監視 judge、本文のある節から最大 8 節、prose-rubric の Q1〜Q6):"
        " 未測定 (key なし)",
    ]


async def test_a_cap_that_is_not_a_number_calls_nothing(tmp_path: Path):
    api = Api()
    result = await _judge(tmp_path, api, env={**KEY, monitor.BUDGET_ENV: "five"})
    assert api.sent == []
    assert result.precision.stop == result.fidelity.stop == "bad-budget"
    assert result.budget is None
    assert "未測定 (JRP_MONITOR_WEEKLY_USD が 0 以上の数でない)" in _shown(result)[0]


# ------------------------------------------------------------------------- calls and answers


async def test_the_answers_are_tallied_priced_and_appended(tmp_path: Path):
    api = Api()
    result = await _judge(tmp_path, api)
    assert result.fidelity == Tally(asked=3, judged=3, passed=2, failed=("akc / memory-eval",))
    assert result.precision == Tally(asked=2, judged=2, passed=1)
    assert result.usd == pytest.approx(5 * USD)
    assert result.week_usd == pytest.approx(5 * USD)
    assert result.rubric_sha == sha(RUBRIC or "")
    assert _shown(result) == [
        "- OUT 精度標本 (監視 judge、O1 の論文から最大 12 本、claim は問いを前に進めるか):"
        " yes+partial 1/2",
        "- W 忠実さの標本 (監視 judge、本文のある節から最大 8 節、prose-rubric の Q1〜Q6):"
        " pass 2/3 · fail: akc / memory-eval",
        "- 監視 judge claude-opus-5-5: 今回 $0.03 · 今週 $0.03 / 上限 $5.00",
    ]
    calls = _ledger(tmp_path)
    assert sorted((c.kind, c.answer) for c in calls) == [
        ("fidelity", "fail"),
        ("fidelity", "pass"),
        ("fidelity", "pass"),
        ("precision", "no"),
        ("precision", "partial"),
    ]
    assert {(c.spent_week, c.week, c.model, c.error) for c in calls} == {
        (SPENT_WEEK, "2026-W45", "anthropic:claude-opus-5-5", None)
    }
    assert all((c.input_tokens, c.output_tokens, c.at) == (1000, 100, NOW) for c in calls)
    assert week_spent(tmp_path / LEDGER_FILE, SPENT_WEEK) == pytest.approx(5 * USD)


async def test_the_requests_carry_the_bench_judge_and_the_precision_question(tmp_path: Path):
    api = Api()
    await _judge(tmp_path, api)
    bodies = [_body(r) for r in api.sent]
    assert {r.headers["x-api-key"] for r in api.sent} == {"sk-ant-test"}
    assert {str(r.url).split("?")[0] for r in api.sent} == {"https://api.anthropic.com/v1/messages"}
    assert {b["model"] for b in bodies} == {"claude-opus-5-5"}
    assert {b["max_tokens"] for b in bodies} == {monitor.MAX_TOKENS}
    assert {b["output_config"]["format"]["type"] for b in bodies} == {"json_schema"}
    fidelity = [b for b in bodies if _kind(b) == "fidelity"]
    assert {b["system"][0]["text"] for b in fidelity} == {JUDGE_INSTRUCTIONS.raw("ja")}
    (eval_prompt,) = [_prompt(b) for b in fidelity if "評価の指標" in _prompt(b)]
    assert eval_prompt.startswith((RUBRIC or "").strip())
    assert "## 材料" in eval_prompt and eval_prompt.endswith("評価の指標 [1]。")
    (c1,) = [_prompt(b) for b in bodies if "<paper>\nc1\n</paper>" in _prompt(b)]
    assert c1.startswith("<question>\n問い: 記憶は何で決まるのか\n</question>\n\n<claim>\n")


async def test_the_brief_and_not_reach_the_precision_judge():
    question = Question.new(
        line="https://example.org/line/akc",
        slug="q",
        version=1,
        title="Which memory designs matter",
        brief="On public benchmarks.",
        negative_topics=("prompt tricks", "RAG"),
        opened_at=NOW,
    )
    prompt = monitor.precision_prompt(Paper("k", "akc", question, "the claim", "the title"), "en")
    assert prompt == (
        "<question>\nQuestion: Which memory designs matter\n"
        "Background of the question: On public benchmarks.\n"
        "What this question is not: prompt tricks / RAG\n</question>\n\n"
        "<claim>\nthe claim\n</claim>\n\n<paper>\nthe title\n</paper>"
    )


# ---------------------------------------------------------------------------------- stops


async def test_the_weeks_cap_stops_the_judge_and_the_rest_is_unmeasured(tmp_path: Path):
    api = Api()
    env = {**KEY, monitor.BUDGET_ENV: "0.009"}  # under it after 1 call, past it after 2
    result = await _judge(tmp_path, api, env=env, concurrency=1)
    assert len(api.sent) == 2
    assert (result.fidelity.asked, result.fidelity.judged, result.fidelity.stop) == (3, 2, "budget")
    assert result.precision == Tally(asked=2, stop="budget")
    shown = _shown(result)
    assert shown[0].endswith("未測定 (今週の上限に達した)")
    assert re.search(r"pass \d/2 · 未測定 1 \(今週の上限に達した\)", shown[1])
    assert shown[2].endswith("今回 $0.01 · 今週 $0.01 / 上限 $0.01")
    assert len(_ledger(tmp_path)) == 2


async def test_spending_earlier_in_the_same_iso_week_counts_toward_the_cap(tmp_path: Path):
    ledger = tmp_path / LEDGER_FILE
    ledger.parent.mkdir(parents=True)
    spent = Call(
        at=NOW - timedelta(hours=1),
        spent_week=SPENT_WEEK,
        week="2026-W44",
        kind="precision",
        item="arxiv:x",
        model=str(MODEL),
        usd=5.0,
    )
    last_week = spent.model_copy(update={"spent_week": "2026-W45", "usd": 100.0})
    rows = [spent.model_dump_json(), last_week.model_dump_json(), '{"cut": ']
    ledger.write_text("\n".join(rows), encoding="utf-8")  # the last line was cut short
    assert week_spent(ledger, SPENT_WEEK) == 5.0
    api = Api()
    result = await _judge(tmp_path, api)
    assert api.sent == []
    assert result.fidelity.stop == result.precision.stop == "budget"
    assert result.week_usd == 5.0
    assert "今回 $0.00 · 今週 $5.00 / 上限 $5.00" in _shown(result)[2]
    ledger.write_text(last_week.model_dump_json() + "\n", encoding="utf-8")
    assert (await _judge(tmp_path, Api())).precision.judged == 2  # another week's spend


async def test_a_429_stops_at_once_and_is_not_retried(tmp_path: Path):
    api = Api(_error(429, "rate_limit_error: slow down"))
    result = await _judge(tmp_path, api, concurrency=1)
    assert len(api.sent) == 1  # neither the SDK nor pydantic-ai sent it again
    assert result.fidelity == Tally(asked=3, stop="rate-limit")
    assert result.precision == Tally(asked=2, stop="rate-limit")
    assert [(c.error, c.usd, c.answer) for c in _ledger(tmp_path)] == [("http 429", 0.0, None)]
    assert _shown(result)[0].endswith("未測定 (429 rate limit、再試行しない)")


async def test_a_429_stops_a_concurrent_burst_within_the_calls_in_flight(tmp_path: Path):
    api = Api(_error(429, "rate_limit_error: slow down"))
    result = await _judge(tmp_path, api)
    assert 1 <= len(api.sent) <= monitor.CONCURRENCY
    assert result.fidelity.judged == result.precision.judged == 0


@pytest.mark.parametrize(
    ("status", "message", "stop", "word"),
    [
        (
            400,
            "Your credit balance is too low to access the Anthropic API.",
            "credit",
            "API クレジット切れ",
        ),
        (401, "invalid x-api-key", "auth", "key が拒否された"),
        (403, "permission denied", "auth", "key が拒否された"),
    ],
    ids=["credits-spent", "bad-key", "forbidden"],
)
async def test_spent_credits_or_a_refused_key_stop_the_judge(
    tmp_path: Path, status: int, message: str, stop: str, word: str
):
    api = Api(_error(status, message))
    result = await _judge(tmp_path, api, concurrency=1)
    assert len(api.sent) == 1
    assert result.fidelity.stop == result.precision.stop == stop
    assert _shown(result)[1].endswith(f"未測定 ({word})")


async def test_another_failure_leaves_its_item_unmeasured_and_the_rest_go_on(tmp_path: Path):
    failed: list[str] = []

    def respond(body: dict[str, Any]) -> httpx2.Response:
        if _kind(body) == "precision" and not failed:
            failed.append(_prompt(body))
            return _error(500, "overloaded")(body)
        if _kind(body) == "fidelity" and "同じ論文" in _prompt(body):
            return _reply(body, {"verdict": "maybe"})  # not a GateVerdict
        return _reply(body, _answer(body))

    api = Api(respond)
    result = await _judge(tmp_path, api, concurrency=1)
    assert len(api.sent) == 5  # one request per item: nothing re-asked
    assert (result.fidelity.judged, result.fidelity.stop) == (2, "error")
    assert (result.precision.judged, result.precision.stop) == (1, "error")
    errors = sorted(c.error or "" for c in _ledger(tmp_path))
    assert errors == ["", "", "", "UnexpectedModelBehavior", "http 500"]
    assert "未測定 1 (呼び出しの失敗)" in _shown(result)[1]


async def test_a_failure_no_branch_names_is_logged_and_raised_as_the_bug_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class Broken:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def run(self, *_: object, **__: object) -> object:
            raise ValueError("a bug")

    monkeypatch.setattr(monitor, "Agent", Broken)
    with pytest.raises(ValueError, match="a bug"):
        await _judge(tmp_path, Api(), concurrency=1)
    assert {c.error for c in _ledger(tmp_path)} == {"raised"}


def test_a_ledger_line_cut_short_is_closed_before_the_next_row(tmp_path: Path):
    ledger = tmp_path / LEDGER_FILE
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"cut": ', encoding="utf-8")
    append_row(ledger, {"usd": 0.5, "note": "a\u2028b"})
    assert lines(ledger) == ['{"cut": ', '{"note": "a\u2028b", "usd": 0.5}']
    assert lines(tmp_path / "none.jsonl") == []


async def test_the_deadline_leaves_what_did_not_finish_unmeasured(tmp_path: Path):
    async def slow(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(10)
        return _reply(_body(request), _answer(_body(request)))

    result = await _judge(tmp_path, slow, deadline_s=0.05)
    assert result.fidelity == Tally(asked=3, stop="deadline")
    assert result.precision == Tally(asked=2, stop="deadline")
    calls = _ledger(tmp_path)
    assert len(calls) == monitor.CONCURRENCY  # the calls in flight when the clock ran out
    assert {(c.error, c.usd) for c in calls} == {("deadline", 0.0)}
    assert _shown(result)[0].endswith("未測定 (時間切れ)")


async def test_without_a_rubric_only_the_precision_sample_is_judged(tmp_path: Path):
    api = Api()
    result = await _judge(tmp_path, api, rubric=None)
    assert {_kind(_body(r)) for r in api.sent} == {"precision"}
    assert result.fidelity == Tally(asked=3, stop="no-rubric")
    assert result.precision.judged == 2
    assert _shown(result)[1].endswith("未測定 (rubric が読めない)")


async def test_an_empty_week_has_nothing_to_sample(tmp_path: Path):
    api = Api()
    result = await _judge(tmp_path, api, sample=Sample("2026-W45", "ja", (), ()))
    assert api.sent == []
    assert result.fidelity == result.precision == Tally(asked=0)
    assert _shown(result)[0].endswith(": 対象なし")


def test_the_monitor_lines_read_in_every_language():
    judged = MonitorResult(
        fidelity=Tally(asked=3, judged=2, passed=1, stop="budget", failed=("akc / q",)),
        precision=Tally(asked=2, stop="rate-limit"),
        usd=0.02,
        week_usd=0.5,
    )
    en = _shown(judged, "en")
    assert [line for line in en if CJK.search(line)] == []
    assert en[1].endswith("pass 1/2 · 1 not measured (this week's cap is reached) · fail: akc / q")
    assert en[0].endswith("not measured (429 rate limit, not retried)")
    zh = _shown(judged, "zh")
    assert zh[2] == "- 监视 judge claude-opus-5-5: 本次 $0.02 · 本周 $0.50 / 上限 $5.00"


async def test_the_writer_turns_the_sdks_own_retries_off_only_when_asked():
    auth = ProseAuth(spec=MODEL, api_key="sk-ant-test")
    async with httpx2.AsyncClient() as http:
        default = Writer(auth, http).model(thinking=True)
        off = Writer(auth, http, max_retries=0).model(thinking=True)
    assert isinstance(default, AnthropicModel) and isinstance(off, AnthropicModel)
    assert (default.client.max_retries, off.client.max_retries) == (2, 0)


# -------------------------------------------------------------------------- the whole review


async def test_the_review_judges_its_week_and_records_it(tmp_path: Path):
    env = {**scenario_on_disk(tmp_path), **KEY}
    store = Path(env["JRP_STORE_DIR"])
    api = Api()
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(api)) as http:
        written = await write_weekly_review(
            env, week=WEEK, out=tmp_path / "out", now=NOW, http=http
        )
    assert len(api.sent) == 5
    text = written.note.read_text(encoding="utf-8")
    assert "pass 2/3 · fail: akc / memory-eval" in text
    assert "yes+partial 1/2" in text
    assert keys_of_text(text) == set() and "jrp:" not in text  # keys stay in the ledger
    (line,) = (store / WEEKLY_FILE).read_text(encoding="utf-8").splitlines()
    row: Any = json.loads(line)
    assert row["monitor"]["fidelity"] == {
        "asked": 3,
        "judged": 3,
        "passed": 2,
        "stop": None,
        "failed": ["akc / memory-eval"],
    }
    assert row["monitor"]["model"] == "anthropic:claude-opus-5-5"
    assert row["monitor"]["rubric_sha"] == sha(RUBRIC or "")
    assert len(_ledger(store)) == 5
