"""The prose bench's automated half (pipeline.prose_eval): the fidelity judge and the
simulated reader, with a fake `ask` in place of `claude -p`."""

from pathlib import Path

from pydantic import BaseModel

from jev_research_pipeline.generation.claude_code import ClaudeCodeError, ClaudeUsageLimit
from jev_research_pipeline.pipeline import prose_bench as pb
from jev_research_pipeline.pipeline import prose_eval as pe

from .test_prose_bench import RUBRIC, _bench  # pyright: ignore[reportPrivateUsage]

READER = pe.ReaderAnswer(
    takeaway="t",
    studies=[
        pe.ReaderStudy(
            name="A",
            problem="p",
            method="m",
            finding="f",
            numbers=[pe.ReaderNumber(value="2倍")],
        )
    ],
    stuck=[pe.Stuck(quote="q", why="説明の無い専門用語")],
)
GRADE = pe.Grade(
    studies=[
        pe.StudyGrade(
            name="A",
            source="S1",
            identified="Yes",
            problem="Yes",
            method="Yes",
            finding="No",
            numbers="Yes",
        )
    ],
    misbeliefs=["限定が落ちた"],
)


class Fake:
    """Answers by output type; records every (model, prompt) it was asked."""

    def __init__(self, *, fail: type[Exception] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    async def __call__(
        self, model: str, instructions: str, prompt: str, output: type[BaseModel]
    ) -> BaseModel:
        self.calls.append((model, prompt))
        if self.fail:
            raise self.fail("limit reached")
        if output is pb.GateVerdict:
            return pb.GateVerdict(verdict="pass")
        return READER if output is pe.ReaderAnswer else GRADE


async def test_the_judge_writes_one_verdict_per_gate_file_once(tmp_path: Path):
    bench = _bench(tmp_path)
    pb.gate_files(bench, "cand", RUBRIC, split="all")
    ask = Fake()
    await pe.judge(bench, "cand", ask, concurrency=2)
    assert [m for m, _ in ask.calls] == [pe.JUDGE_MODEL]
    assert "## 草稿" in ask.calls[0][1]  # the whole gate file is the prompt
    assert pb.gate_summary(bench, "cand")[0] == "cand: pass 1 / fail 0 / judged 1"
    await pe.judge(bench, "cand", ask, concurrency=2)
    assert len(ask.calls) == 1  # already judged: not asked again


async def test_the_reader_sees_only_the_draft_and_the_grader_only_the_materials(tmp_path: Path):
    bench = _bench(tmp_path)
    ask = Fake()
    await pe.comprehend(bench, "cand", ask, concurrency=1)
    (reader_model, reader_prompt), (grader_model, grader_prompt) = ask.calls
    assert (reader_model, grader_model) == (pe.READER_MODEL, pe.GRADER_MODEL)
    assert "<draft>" in reader_prompt and "<materials>" not in reader_prompt
    assert "<materials>" in grader_prompt and "<draft>" not in grader_prompt
    assert '"name": "A"' in grader_prompt  # the reader's answer, not the draft


async def test_scores_compare_variants_on_the_same_cases(tmp_path: Path):
    bench = _bench(tmp_path)
    ask = Fake()
    for v in ("base", "cand"):
        pb.gate_files(bench, v, RUBRIC, split="all")
        await pe.judge(bench, v, ask, concurrency=1)
        await pe.comprehend(bench, v, ask, concurrency=1)
    s = pe.scores(bench, "cand")
    assert (s.cases, s.judged, s.passed, s.comprehended) == (1, 1, 1, 1)
    assert s.facts == 0.8 and s.misbeliefs == 1 and s.stuck == 1.0
    table = pe.scores_table(bench, ["base", "cand"])
    assert table[0].startswith("variant |") and len(table) == 3
    assert table[2].startswith("cand | 1 | 1/1 | 0.800 (1) | 1 | 1.00 |")


def test_a_reader_who_names_nothing_got_nothing_across():
    empty = pe.Comprehension(case="c", variant="v", reader=pe.ReaderAnswer(), grade=pe.Grade())
    assert empty.facts == 0.0


async def test_a_usage_limit_stops_the_burst_and_other_errors_are_reported(tmp_path: Path):
    bench = _bench(tmp_path)
    lines = await pe.comprehend(bench, "cand", Fake(fail=ClaudeUsageLimit), concurrency=1)
    assert lines[0].startswith("STOPPED: usage limit")
    assert not list(pe.comprehend_dir(bench, "cand").glob("*.json"))
    lines = await pe.comprehend(bench, "cand", Fake(fail=ClaudeCodeError), concurrency=1)
    assert any(line.startswith("error:") for line in lines)
