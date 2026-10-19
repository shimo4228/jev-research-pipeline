"""A store written by an older build (judge, 2026-09-23: an old store stopped the whole run
with a bare ValueError). An @context that only gained terms is migrated in place; any
other difference stops the run with one line that says what to do."""

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from jev_research_pipeline.cli import main
from jev_research_pipeline.model import Label, Report, RotationCursor
from jev_research_pipeline.model.jsonld import CONTEXT
from jev_research_pipeline.pipeline.runner import run_pipeline
from jev_research_pipeline.store import GraphStore
from jev_research_pipeline.store.migrate import (
    StoreSchemaError,
    inspect_partition,
    migrate_store,
    prepare_store,
)

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_world
from .test_e2e import env as env  # the fixture, re-exported

GOLDEN = Path(__file__).parent / "golden" / "store"
ADDITIVE = GOLDEN / "old-context-additive.jsonld"
INCOMPATIBLE = GOLDEN / "old-context-incompatible.jsonld"
REPORT_LABEL = GOLDEN / "report-label-fa67ed5.jsonld"
ADDED = len(CONTEXT) - len(json.loads(ADDITIVE.read_text(encoding="utf-8"))["@context"])
# Terms today's CONTEXT has beyond the golden: it grows with every node kind.


def _store(tmp_path: Path, *, pipeline: Path | None = None, line: Path | None = None) -> Path:
    root = tmp_path / "store"
    (root / "lines").mkdir(parents=True)
    if pipeline is not None:
        shutil.copy(pipeline, root / "pipeline.jsonld")
    if line is not None:
        shutil.copy(line, root / "lines" / "akc.jsonld")
    return root


def test_the_goldens_are_what_they_claim():
    old = json.loads(ADDITIVE.read_text(encoding="utf-8"))["@context"]
    assert old != CONTEXT
    assert set(old) < set(CONTEXT)
    assert all(CONTEXT[k] == v for k, v in old.items())


def test_the_report_label_golden_is_what_it_claims():
    doc = json.loads(REPORT_LABEL.read_text(encoding="utf-8"))
    # Every term the fa67ed5 build wrote stays in CONTEXT with its value: a removed or
    # re-mapped term makes every partition incompatible and stops the 05:00 run.
    assert set(doc["@context"]) <= set(CONTEXT)
    assert all(CONTEXT[k] == v for k, v in doc["@context"].items())
    reports = [n for n in doc["@graph"] if n["@type"] == "Report"]
    labels = [n for n in doc["@graph"] if n["@type"] == "Label"]
    assert len(reports) == 2 and len(labels) == 3
    assert [r["operations"]["claude_calls"] for r in reports] == [0, 0]
    golds = [m["gold_agreement"] for r in reports for m in r["operations"]["rubric"]]
    assert 1.0 in golds and None in golds
    assert [label["provenance"] for label in labels].count("question_day") == 2


def _same_report(node: Report, old: dict[str, Any]) -> None:
    assert (
        node.line,
        node.run_date.isoformat(),
        node.rendering,
        node.prose,
        list(node.claims),
        list(node.unjudged),
        node.partial,
    ) == tuple(
        old[k] for k in ("line", "run_date", "rendering", "prose", "claims", "unjudged", "partial")
    )
    ops, was = node.operations, old["operations"]
    assert (
        ops.jev_questions,
        ops.generation_input_tokens,
        ops.generation_output_tokens,
        ops.cost_usd,
        ops.fill_rate_previous,
    ) == tuple(
        was[k]
        for k in (
            "jev_questions",
            "generation_input_tokens",
            "generation_output_tokens",
            "cost_usd",
            "fill_rate_previous",
        )
    )
    assert [(m.axis, m.mean_score) for m in ops.rubric] == [
        (m["axis"], m["mean_score"]) for m in was["rubric"]
    ]


def _same_label(node: Label, old: dict[str, Any]) -> None:
    assert (node.subject, node.report, node.verdict, node.provenance) == tuple(
        old[k] for k in ("subject", "report", "verdict", "provenance")
    )
    assert node.harvested_at == datetime.fromisoformat(old["harvested_at"])


def test_old_reports_and_labels_validate_and_survive_a_rewrite(tmp_path: Path):
    """The Reports and Labels a store already holds (98 Reports on 2026-10-20, all with
    claude_calls 0) read under today's model and come back from the migration's rewrite
    with their data. Fields a later model retires (claude_calls, gold_agreement) only have
    to validate here, not to survive the rewrite."""
    assert inspect_partition(REPORT_LABEL).verdict in ("current", "additive")
    root = _store(tmp_path, line=REPORT_LABEL)
    prepare_store(root)  # rewrites the file once CONTEXT has grown past fa67ed5
    part = GraphStore(root).line("akc")
    assert inspect_partition(part.path).verdict == "current"
    nodes = part.load()
    part.write_all(list(nodes.values()))  # the same rewrite, run on today's model
    assert part.load() == nodes
    raw = {n["@id"]: n for n in json.loads(REPORT_LABEL.read_text(encoding="utf-8"))["@graph"]}
    assert set(nodes) == set(raw)
    for iri, node in nodes.items():
        match node:
            case Report():
                _same_report(node, raw[iri])
            case Label():
                _same_label(node, raw[iri])
            case _:
                pytest.fail(f"unexpected node in the golden: {iri}")


def test_an_old_context_that_only_lacks_terms_is_additive():
    found = inspect_partition(ADDITIVE)
    assert found.verdict == "additive"
    old = json.loads(ADDITIVE.read_text(encoding="utf-8"))["@context"]
    # The count follows CONTEXT: every added term (Sighting, UsedMark, ...) joins it.
    assert f"{len(CONTEXT) - len(old)} 項目" in found.detail


def test_an_old_node_the_model_no_longer_accepts_is_incompatible():
    found = inspect_partition(INCOMPATIBLE)
    assert found.verdict == "incompatible"
    assert "claim_detection" in found.detail


def test_a_changed_or_removed_term_is_incompatible(tmp_path: Path):
    doc = json.loads(ADDITIVE.read_text(encoding="utf-8"))
    doc["@context"]["title"] = "https://schema.org/name"
    changed = tmp_path / "changed.jsonld"
    changed.write_text(json.dumps(doc), encoding="utf-8")
    assert inspect_partition(changed).verdict == "incompatible"

    doc = json.loads(ADDITIVE.read_text(encoding="utf-8"))
    doc["@context"]["retired_term"] = "https://example.org/x"
    removed = tmp_path / "removed.jsonld"
    removed.write_text(json.dumps(doc), encoding="utf-8")
    assert inspect_partition(removed).verdict == "incompatible"


def test_the_run_migrates_an_additive_store_and_reads_it(tmp_path: Path):
    root = _store(tmp_path, pipeline=ADDITIVE)
    notes = prepare_store(root)
    assert notes == [
        f"store: pipeline.jsonld を現行 schema に移行 (@context に {ADDED} 項目を追加)"
    ]
    doc = json.loads((root / "pipeline.jsonld").read_text(encoding="utf-8"))
    assert doc["@context"] == CONTEXT
    (cursor,) = GraphStore(root).pipeline().load().values()
    assert isinstance(cursor, RotationCursor) and cursor.next_slug == "edge"
    assert prepare_store(root) == []  # already current: nothing to say, nothing written


def test_the_run_stops_on_an_incompatible_store_with_one_line(tmp_path: Path):
    root = _store(tmp_path, line=INCOMPATIBLE)
    before = (root / "lines" / "akc.jsonld").read_bytes()
    with pytest.raises(StoreSchemaError) as raised:
        prepare_store(root)
    message = str(raised.value)
    assert "\n" not in message
    assert message.startswith("store/lines/akc.jsonld は旧 schema")
    assert "`jrp migrate`" in message and "退避" in message
    assert (root / "lines" / "akc.jsonld").read_bytes() == before  # untouched


def test_loading_an_old_partition_names_the_file_instead_of_a_bare_value_error(tmp_path: Path):
    root = _store(tmp_path, line=INCOMPATIBLE)
    with pytest.raises(StoreSchemaError, match=r"store/lines/akc\.jsonld"):
        GraphStore(root).line("akc").load()


def test_migrate_dry_run_changes_nothing(tmp_path: Path):
    root = _store(tmp_path, pipeline=ADDITIVE, line=INCOMPATIBLE)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    lines = migrate_store(root, dry_run=True, today=date(2026, 9, 23))
    assert lines == [
        "lines/akc.jsonld: 非互換 → 退避予定 retired/2026-09-23/lines/akc.jsonld "
        + f"({inspect_partition(INCOMPATIBLE).detail})",
        f"pipeline.jsonld: 移行予定 (@context に {ADDED} 項目を追加)",
    ]
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_migrate_rewrites_the_additive_and_retires_the_incompatible(tmp_path: Path):
    root = _store(tmp_path, pipeline=ADDITIVE, line=INCOMPATIBLE)
    (root / "index").mkdir()
    (root / "index" / "akc.sqlite").write_bytes(b"derived")

    lines = migrate_store(root, dry_run=False, today=date(2026, 9, 23))

    assert lines[0].startswith(
        "lines/akc.jsonld: 非互換 → 退避 retired/2026-09-23/lines/akc.jsonld"
    )
    assert lines[1] == f"pipeline.jsonld: 移行 (@context に {ADDED} 項目を追加)"
    retired = root / "retired" / "2026-09-23"
    assert (retired / "lines" / "akc.jsonld").read_bytes() == INCOMPATIBLE.read_bytes()
    assert not (root / "lines" / "akc.jsonld").exists()
    # The index is derived from the partition, so it leaves with it.
    assert (retired / "index" / "akc.sqlite").read_bytes() == b"derived"
    assert prepare_store(root) == []  # the next run starts on a clean store


def test_cli_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    root = _store(tmp_path, pipeline=ADDITIVE)
    monkeypatch.setenv("JRP_STORE_DIR", str(root))
    assert main(["migrate", "--dry-run"]) == 0
    assert "pipeline.jsonld: 移行予定" in capsys.readouterr().out
    assert main(["migrate"]) == 0
    assert "pipeline.jsonld: 移行 (" in capsys.readouterr().out
    assert main(["migrate"]) == 0
    assert capsys.readouterr().out == "store は現行 schema\n"


def test_cli_stops_any_command_on_an_incompatible_store_with_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    root = _store(tmp_path, line=INCOMPATIBLE)
    monkeypatch.setenv("JRP_STORE_DIR", str(root))
    monkeypatch.setenv("JRP_DAILY_RESEARCH_CONFIG", str(tmp_path / "absent.toml"))
    assert main(["fit"]) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "旧 schema" in err


async def test_a_run_on_an_incompatible_store_stops_before_it_writes_anything(
    env: dict[str, str], cassette: ClientFactory
):
    root = Path(env["JRP_STORE_DIR"])
    (root / "lines").mkdir(parents=True)
    shutil.copy(INCOMPATIBLE, root / "lines" / "akc.jsonld")
    with pytest.raises(StoreSchemaError, match=r"store/lines/akc\.jsonld は旧 schema"):
        await run_pipeline(env, now=b.T0, http=cassette(fake_world()), pacing=False)
    assert list(Path(env["JRP_VAULT_DIR"]).rglob("*.md")) == []
    assert not (root / "pipeline.jsonld").exists()  # the rotation did not advance
