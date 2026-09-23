"""Prose bench: cases from the store, code gates, blind pairs, and the two-order tally."""

import json
from pathlib import Path

from jev_research_pipeline.pipeline import prose_bench as pb
from jev_research_pipeline.qwen.prose import INFERENCE_MARK, NO_DIRECT_EVIDENCE

from . import builders as b

RUBRIC = (Path(__file__).parents[1] / "docs" / "prose-rubric.md").read_text(encoding="utf-8")


def _nodes() -> dict[str, object]:
    nodes = [b.source(), b.unit(), b.claim(), b.question(), b.question_log(), b.report()]
    return {n.id: n for n in nodes}


def test_a_question_day_becomes_a_case_with_its_claims_source_and_baseline():
    (case,) = pb.cases_from_nodes(
        "akc",
        _nodes(),  # pyright: ignore[reportArgumentType]
        line_name="AKC",
        vocabulary=("agent memory",),
    )
    assert case.question_title == b.question().title
    assert [c.text for c in case.claims] == [b.claim().text]
    assert case.claims[0].source == 1
    assert case.sources[0].title == b.source().title
    assert case.baseline == "今日の変化。"
    assert case.known == ()  # the claim is today's, not earlier evidence


def test_split_depends_on_the_id_alone_and_dedups():
    (case,) = pb.cases_from_nodes(
        "akc",
        _nodes(),  # pyright: ignore[reportArgumentType]
        line_name="AKC",
        vocabulary=(),
    )
    many = [case.model_copy(update={"id": f"{i:012x}"}) for i in range(6)]
    first = {c.id: c.split for c in pb.split_cases([*many, many[0]])}
    assert len(first) == 6
    assert first["000000000000"] == "holdout" and first["000000000001"] == "dev"
    # a later export with more cases moves none of the earlier ones
    later = pb.split_cases([*many, case.model_copy(update={"id": "0000000000ff"})])
    assert all(first[c.id] == c.split for c in later if c.id in first)


def test_gates_are_facts_about_marks_and_citations():
    good = f"主張がある [1]。\n\n{INFERENCE_MARK}だから次を確かめる。"
    assert pb.gates(good, 1) == ()
    assert pb.gates(f"{NO_DIRECT_EVIDENCE}\n\n{INFERENCE_MARK}橋。", 1) == ("引用が 1 つも無い",)
    assert "推論段落が最後に 1 つではない" in pb.gates("主張 [1]。", 1)
    assert "推論段落に [n] がある" in pb.gates(f"主張 [1]。\n\n{INFERENCE_MARK}推論 [1]。", 1)
    assert "引用の無い根拠段落がある" in pb.gates(f"主張 2 件。\n\n{INFERENCE_MARK}推論。", 1)
    # a source-excerpt citation and a short figure-free framing sentence both count
    framed = f"Jev の名は出てこないが、以下は較正の知見である。\n\n抜粋の事実 (S1)。主張 [1]。\n\n{INFERENCE_MARK}推論。"
    assert pb.gates(framed, 1) == ()


def _bench(tmp_path: Path) -> Path:
    (case,) = pb.cases_from_nodes(
        "akc",
        _nodes(),  # pyright: ignore[reportArgumentType]
        line_name="AKC",
        vocabulary=(),
    )
    (tmp_path / "cases").mkdir(parents=True)
    (tmp_path / "cases" / f"{case.id}.json").write_text(case.model_dump_json(), encoding="utf-8")
    for variant, prose in (
        ("base", "短い [1]。"),
        ("cand", f"長い [1]。\n\n{INFERENCE_MARK}推論。"),
    ):
        pb.write_draft(
            tmp_path,
            pb.Draft(
                case=case.id,
                variant=variant,
                prose=prose,
                failure=None,
                seconds=1.0,
                chars=len(prose),
                gates=pb.gates(prose, 1),
            ),
        )
    return tmp_path


def test_pairs_are_blind_both_orders_with_the_rubric_inside(tmp_path: Path):
    out = pb.make_pairs(_bench(tmp_path), "base", "cand", RUBRIC, split="all")
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    assert len(key) == 2
    assert {k["X"] for k in key.values()} == {"base", "cand"}  # each variant first once
    text = next(out.glob("*.md")).read_text(encoding="utf-8")
    assert "base" not in text and "cand" not in text  # variant names never shown
    assert "### 統合" in text and "## 草稿X" in text and "## 材料" in text


def _verdict(winner: str, gate_y: str = "pass") -> str:
    axis = {"winner": winner, "quote_x": "", "quote_y": "", "why": ""}
    return json.dumps(
        {
            "gate": {"X": "pass", "Y": gate_y},
            "axes": {"統合": axis, "日本語": {**axis, "winner": "tie"}},
            "overall": axis,
        }
    )


def test_an_axis_is_won_only_when_both_orders_agree(tmp_path: Path):
    out = pb.make_pairs(_bench(tmp_path), "base", "cand", RUBRIC, split="all")
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    (out / "verdicts").mkdir()
    for name, k in key.items():
        # the judge prefers "cand" in both orders, wherever it sits
        winner = "X" if k["X"] == "cand" else "Y"
        (out / "verdicts" / f"{name}.json").write_text(_verdict(winner), encoding="utf-8")
    lines = pb.tally(out, "base", "cand")
    assert "総合: base 0 / cand 1 / tie 0" in lines
    assert "統合: base 0 / cand 1 / tie 0" in lines
    assert "日本語: base 0 / cand 0 / tie 1" in lines


def test_a_split_decision_across_orders_is_a_tie(tmp_path: Path):
    out = pb.make_pairs(_bench(tmp_path), "base", "cand", RUBRIC, split="all")
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    (out / "verdicts").mkdir()
    for name in key:
        (out / "verdicts" / f"{name}.json").write_text(_verdict("X"), encoding="utf-8")
    assert "統合: base 0 / cand 0 / tie 1" in pb.tally(out, "base", "cand")


def test_both_drafts_failing_the_gate_is_an_overall_tie(tmp_path: Path):
    out = pb.make_pairs(_bench(tmp_path), "base", "cand", RUBRIC, split="all")
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    (out / "verdicts").mkdir()
    for name, k in key.items():
        winner = "X" if k["X"] == "cand" else "Y"
        body = json.loads(_verdict(winner))
        body["gate"] = {"X": "fail", "Y": "fail"}
        (out / "verdicts" / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")
    assert "総合: base 0 / cand 0 / tie 1" in pb.tally(out, "base", "cand")


def test_an_axis_missing_from_one_order_is_a_tie(tmp_path: Path):
    out = pb.make_pairs(_bench(tmp_path), "base", "cand", RUBRIC, split="all")
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    (out / "verdicts").mkdir()
    for i, (name, k) in enumerate(key.items()):
        body = json.loads(_verdict("X" if k["X"] == "cand" else "Y"))
        if i == 1:
            del body["axes"]["統合"]
        (out / "verdicts" / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")
    assert "統合: base 0 / cand 0 / tie 1" in pb.tally(out, "base", "cand")
