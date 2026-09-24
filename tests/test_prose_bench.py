"""Prose bench: cases from the store, code gates, blind pairs, and the two-order tally."""

import json
from pathlib import Path

from jev_research_pipeline.generation.prose import INFERENCE_MARK, NO_DIRECT_EVIDENCE
from jev_research_pipeline.pipeline import prose_bench as pb

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


def test_gate_files_hold_rubric_materials_one_draft_and_the_current_code_check(tmp_path: Path):
    out, n = pb.gate_files(_bench(tmp_path), "base", RUBRIC, split="all")
    assert n == 1
    (text,) = [p.read_text(encoding="utf-8") for p in out.glob("*.md")]
    assert "Q1 数値" in text and "## 材料" in text and "## 草稿" in text
    assert "短い [1]。" in text
    # the stored draft had no inference paragraph: the check is re-run and shown
    assert "コード検査: 不合格(推論段落が最後に 1 つではない)" in text


def test_gate_summary_counts_and_lists_the_failures(tmp_path: Path):
    verdicts = tmp_path / "v"
    verdicts.mkdir()
    (verdicts / "c1.json").write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")
    (verdicts / "c2.json").write_text(
        json.dumps({"verdict": "fail", "reason": "Q1: 比較の相手が違う"}), encoding="utf-8"
    )
    assert pb.gate_summary(tmp_path, "base", verdicts) == [
        "base: pass 1 / fail 1 / judged 2",
        "fail: c2 Q1: 比較の相手が違う",
    ]


def test_the_reading_file_hides_variant_names_and_keeps_the_key_beside_it(tmp_path: Path):
    bench = _bench(tmp_path)
    out, n = pb.read_file(bench, ["base", "cand"], tmp_path / "read.md", split="all")
    assert n == 1
    text = out.read_text(encoding="utf-8")
    assert "base" not in text and "cand" not in text
    assert "### A" in text and "### B" in text and "一番良いのはどれか" in text
    key = json.loads(out.with_suffix(".key.json").read_text(encoding="utf-8"))
    assert set(key["case1"].values()) >= {"base", "cand"}


def test_a_single_variant_reading_file_asks_whether_it_reads(tmp_path: Path):
    out, _ = pb.read_file(_bench(tmp_path), ["cand"], tmp_path / "one.md", split="all")
    text = out.read_text(encoding="utf-8")
    assert "読めるか" in text and "### A" not in text
