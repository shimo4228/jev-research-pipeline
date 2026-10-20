"""One RunRecord per tick in the pipeline partition (plan quality-metrics, claim 5): the
lines the tick set out to run, the DEGRADED reasons, whether a notification channel was
set, and per note what its Report does not keep — the prefilter's question order, the
Review sources, each section's rendering, the dropped [n]s. No cassette: the fake world
answers directly, and the clock is fixed."""

import json
import re
import shutil
from datetime import date, datetime, timedelta
from itertools import product
from pathlib import Path

import httpx2
import pytest
from pydantic import ValidationError

from jev_research_pipeline.jev import question_prefilter
from jev_research_pipeline.model import (
    Judgment,
    LineRecord,
    Question,
    QuestionLog,
    RotationCursor,
    RunRecord,
    SectionRendering,
    SourceItem,
)
from jev_research_pipeline.pipeline.config import env_tracks, line_context
from jev_research_pipeline.pipeline.notify import MACOS_ENV, NOTIFY_ENV, WEBHOOK_ENV, configured
from jev_research_pipeline.pipeline.notify import notify as send
from jev_research_pipeline.pipeline.run import LineOutcome, LineRun
from jev_research_pipeline.pipeline.runner import run_pipeline
from jev_research_pipeline.questions import open_questions
from jev_research_pipeline.store import GraphStore, input_sha256

from . import builders as b
from .conftest import Handler
from .fakes import fake_jev, fake_world
from .test_e2e import env as env  # the fixture, re-exported
from .test_migrate import ADDITIVE

END = b.T0 + timedelta(minutes=17)


def _end() -> datetime:
    return END


def _client(handler: Handler | None = None) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler or fake_world()))


def _records(env: dict[str, str]) -> list[RunRecord]:
    nodes = GraphStore(Path(env["JRP_STORE_DIR"])).pipeline().load().values()
    return [n for n in nodes if isinstance(n, RunRecord)]


def _logs(env: dict[str, str]) -> list[QuestionLog]:
    nodes = GraphStore(Path(env["JRP_STORE_DIR"])).line("akc").load().values()
    return [n for n in nodes if isinstance(n, QuestionLog)]


async def test_a_tick_puts_one_run_record_with_its_lines_and_notes(env: dict[str, str]):
    (outcome,) = await run_pipeline(env, now=b.T0, http=_client(), pacing=False, clock=_end)
    (record,) = _records(env)
    assert record.id == RunRecord.id_for(b.T0.date(), b.T0)
    assert (record.run_date, record.started_at, record.finished_at) == (b.T0.date(), b.T0, END)
    # The rotation's one line, then the daily track; jev has no question file, so it wrote
    # no note: no LineRecord and no reason (the CLI lists it as skipped).
    assert record.lines == ("akc", "jev")
    assert record.reasons == ()
    assert not record.notify_configured
    assert record.line_records == (outcome.record,)

    line = outcome.record
    report = outcome.report
    assert (line.slug, line.report, line.claim_count) == ("akc", report.id, len(report.claims))
    assert line.claim_count > 0
    assert line.questions == (Question.id_for(report.line, "agent-memory", 1),)
    assert line.review == ()  # the fake world keeps every source it screens
    (log,) = _logs(env)
    assert log.text  # the section has prose, and its rendering says how it got it
    assert line.renderings == (SectionRendering(question=log.question, rendering="prose"),)
    assert line.invalid_citations == 0


async def test_every_tick_keeps_its_own_record_and_a_rerun_of_the_same_tick_replaces_it(
    env: dict[str, str],
):
    await run_pipeline(env, now=b.T0, http=_client(), pacing=False, clock=_end)
    (first,) = _records(env)
    assert first.lines == ("akc", "jev")
    # The same `now` again: the same (run_date, started_at), so the same @id. The rotation
    # moved on to edge, and that record replaced the first.
    await run_pipeline(env, now=b.T0, http=_client(), pacing=False, clock=_end)
    (again,) = _records(env)
    assert again.id == first.id and again.lines == ("edge", "jev")
    later = b.T0 + timedelta(hours=3)
    await run_pipeline(env, now=later, http=_client(), pacing=False, clock=_end)
    by_start = {r.started_at: r.lines for r in _records(env)}
    assert by_start == {b.T0: ("edge", "jev"), later: ("akc", "jev")}


def _questions(env: dict[str, str], n: int) -> None:
    body = "".join(
        f"## 問い {i} は何で決まるのか\n- slug: q{i}\n- version: 1\n- status: open\n"
        f"- brief: 記憶機構の違い {i} が下流の精度をどれだけ動かすか。\n- arxiv: agent memory {i}\n\n"
        for i in range(n)
    )
    Path(env["JRP_QUESTIONS_DIR"], "akc.md").write_text(
        f"<!-- jrp:questions:akc -->\n\n{body}", encoding="utf-8"
    )


async def test_questions_are_in_the_order_the_prefilter_asked_them(env: dict[str, str]):
    """questions[i] is the question behind q{i}_on_topic: the day's prefilter Judgments
    hash the state built from the questions in the record's order, and only in that order."""
    _questions(env, 4)
    (outcome,) = await run_pipeline(env, now=b.T0, http=_client(), pacing=False, clock=_end)
    ctx = line_context(next(t for t in env_tracks(env) if t.slug == "akc"))
    by_id = {q.id: q for q in open_questions(env, "akc", line=ctx.line.id, now=b.T0)}
    ordered = [by_id[i] for i in outcome.record.questions]
    assert [q.slug for q in ordered] == ["q0", "q1", "q2", "q3"]
    nodes = GraphStore(Path(env["JRP_STORE_DIR"])).line("akc").load()
    prefiltered = [
        n for n in nodes.values() if isinstance(n, Judgment) and n.function == "question_prefilter"
    ]
    assert prefiltered
    for judgment in prefiltered:
        source = nodes[judgment.subjects[0]]
        assert isinstance(source, SourceItem)
        assert input_sha256(question_prefilter.state(ctx, source, ordered)) == (
            judgment.state_sha256
        )
        assert input_sha256(question_prefilter.state(ctx, source, ordered[::-1])) != (
            judgment.state_sha256
        )


async def test_review_holds_the_notes_review_sources_in_note_order(env: dict[str, str]):
    """The screen sends every source to Review (weighted 0.53, inside the band below the
    0.6 cut): the record's review is the note's Review, mark for mark."""
    world = fake_world()
    borderline = fake_jev(
        {
            "on_topic": 0.97,
            "method_transferable": 0.97,
            "evidence_compatible": 0.97,
            "problem_overlap": (0.0, 0.0, 1.0, 0.0),
            "evidence_strength": (0.0, 1.0, 0.0, 0.0),
            "novelty_vs_evidence_set": (0.0, 1.0, 0.0),
        }
    )

    async def screened_to_review(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.typesafe.ai" and b"problem_overlap" in request.content:
            return await borderline(request)
        return await world(request)

    (outcome,) = await run_pipeline(
        env, now=b.T0, http=_client(screened_to_review), pacing=False, clock=_end
    )
    note = outcome.note.read_text(encoding="utf-8")
    marks = tuple(re.findall(r"jrp:source:(\S+) -->", note))
    assert marks and outcome.record.review == marks
    assert outcome.health.review == len(marks)
    assert outcome.record.claim_count == 0 and outcome.record.renderings == ()


async def test_reasons_name_each_degraded_line(env: dict[str, str]):
    env["JRP_COST_CAP_USD"] = "0"
    env["JRP_JEV_USD_PER_QUESTION"] = "0.001"
    (outcome,) = await run_pipeline(env, now=b.T0, http=_client(), pacing=False, clock=_end)
    (record,) = _records(env)
    assert record.reasons == (
        "akc: empty note (no claim, no review)",
        "akc: cost cap reached (partial note)",
    )
    assert record.reasons == tuple(f"akc: {r}" for r in outcome.health.reasons())
    (line,) = record.line_records
    assert (line.claim_count, line.review, line.renderings) == (0, (), ())


async def test_a_line_that_raised_has_a_reason_and_no_line_record(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
):
    async def boom(self: LineRun) -> LineOutcome:
        raise RuntimeError("boom  went\nthe line")

    monkeypatch.setattr(LineRun, "execute", boom)
    failed: list[str] = []
    assert (
        await run_pipeline(env, now=b.T0, http=_client(), pacing=False, failed=failed, clock=_end)
        == []
    )
    (record,) = _records(env)
    assert record.lines == ("akc", "jev")
    assert record.reasons == ("akc: raised (RuntimeError: boom went the line)",)
    assert record.line_records == ()
    assert failed == ["akc: 失敗 (RuntimeError: boom went the line)"]  # the CLI's line is kept


async def test_the_dropped_citations_are_counted_per_draft(env: dict[str, str]):
    """The writer cites a claim [9] that its section does not have: check_citations drops it
    from every draft, and the record counts what was dropped."""
    world = fake_world()

    async def cites_nine(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "dashscope-intl.aliyuncs.com":
            body = json.loads(request.content)
            if body["model"] == "qwen3.7-max":
                answer = await world(request)
                data = json.loads(answer.content)
                text = data["choices"][0]["message"]["content"]
                data["choices"][0]["message"]["content"] = text.replace("[1]", "[1] [9]")
                return httpx2.Response(200, json=data)
        return await world(request)

    (outcome,) = await run_pipeline(
        env, now=b.T0, http=_client(cites_nine), pacing=False, clock=_end
    )
    (log,) = _logs(env)
    assert "[9]" not in log.text
    assert outcome.health.drafts >= 1
    assert outcome.record.invalid_citations == outcome.health.drafts


async def test_a_template_section_is_recorded_as_template(env: dict[str, str]):
    async def no_prose(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "dashscope-intl.aliyuncs.com":
            if json.loads(request.content)["model"] == "qwen3.7-max":
                return httpx2.Response(400, json={"error": {"message": "Request timed out"}})
        return await fake_world()(request)

    (outcome,) = await run_pipeline(env, now=b.T0, http=_client(no_prose), pacing=False)
    (log,) = _logs(env)
    assert log.text == ""
    assert outcome.record.renderings == (
        SectionRendering(question=log.question, rendering="template"),
    )
    (record,) = _records(env)
    assert record.finished_at is not None and record.finished_at.tzinfo is not None


async def test_notify_configured_follows_the_env_and_is_false_for_a_try(env: dict[str, str]):
    env[MACOS_ENV] = "1"
    await run_pipeline(env, now=b.T0, http=_client(), pacing=False, clock=_end)
    later = b.T0 + timedelta(hours=1)
    await run_pipeline(env, now=later, http=_client(), pacing=False, only=["akc"], clock=_end)
    by_start = {r.started_at: r for r in _records(env)}
    assert by_start[b.T0].notify_configured
    assert by_start[later].lines == ("akc",)
    assert not by_start[later].notify_configured  # `jrp try` notifies nobody


@pytest.mark.parametrize(
    ("webhook", "macos", "script"),
    list(product(["", "https://hooks.example/x"], ["", "1", "0"], ["", "1"])),
)
def test_configured_is_what_notify_returns(webhook: str, macos: str, script: str):
    env = {k: v for k, v in ((WEBHOOK_ENV, webhook), (MACOS_ENV, macos), (NOTIFY_ENV, script)) if v}
    sent = send("t", "b", env=env, runner=lambda _: None, poster=lambda _u, _p: None)
    assert configured(env) == sent == bool(webhook or macos == "1" or script == "1")


async def test_a_store_without_run_records_runs_and_gets_one(env: dict[str, str]):
    """A pipeline partition written before RunRecord (the 2026-09-23 golden: one cursor,
    an older @context) is migrated and read, and the tick adds its record beside the
    cursor."""
    root = Path(env["JRP_STORE_DIR"])
    root.mkdir()
    shutil.copy(ADDITIVE, root / "pipeline.jsonld")
    # The golden's cursor resumes at edge, which has no question: no note, still a record.
    assert await run_pipeline(env, now=b.T0, http=_client(), pacing=False, clock=_end) == []
    nodes = GraphStore(root).pipeline().load().values()
    assert {RotationCursor, RunRecord} <= {type(n) for n in nodes}  # beside the Sightings
    (record,) = _records(env)
    assert (record.lines, record.reasons, record.line_records) == (("edge", "jev"), (), ())


def test_the_record_is_identified_by_its_tick():
    record = b.run_record()
    assert record.id == RunRecord.new(started_at=b.T0).id
    assert record.id != RunRecord.new(started_at=b.T0 + timedelta(seconds=1)).id
    assert RunRecord.new(started_at=b.T0).line_records == ()


def test_run_date_is_the_start_date_and_line_records_belong_to_its_lines():
    raw = b.run_record().model_dump(by_alias=True)
    day = date(2026, 9, 21)
    with pytest.raises(ValidationError, match="started_at's date"):
        RunRecord.model_validate(raw | {"run_date": day, "@id": RunRecord.id_for(day, b.T0)})
    with pytest.raises(ValidationError, match="one of lines"):
        RunRecord.new(started_at=b.T0, lines=("edge",), line_records=b.run_record().line_records)


def test_line_record_iris_have_their_kinds():
    good = b.run_record().line_records[0]
    for field, bad in [
        ("report", b.source().id),
        ("questions", (b.claim().id,)),
        ("questions", (b.question().id, b.question().id)),
        ("review", (b.claim().id,)),
    ]:
        with pytest.raises(ValidationError):
            LineRecord.model_validate(good.model_dump() | {field: bad})
    with pytest.raises(ValidationError, match="Question IRI"):
        SectionRendering(question=b.source().id, rendering="prose")
