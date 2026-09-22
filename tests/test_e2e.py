"""End-to-end (Step 10): one line through a tmp vault on cassette replay, then a tick
edited in the note becomes a Label on the next run's harvest."""

import json
from pathlib import Path

import pytest

from jev_research_pipeline.model import Label, Report
from jev_research_pipeline.pipeline.runner import run_pipeline
from jev_research_pipeline.report import harvest_text
from jev_research_pipeline.store import GraphStore

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_world
from .test_config import CONFIG, GRAPH


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    repo = tmp_path / "agent-knowledge-cycle"
    repo.mkdir()
    (repo / "graph.jsonld").write_text(json.dumps(GRAPH), encoding="utf-8")
    edge = tmp_path / "edge-frontier"
    edge.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        CONFIG.format(repo_akc=repo, repo_edge=edge).replace(
            "lines_per_day = 3", "lines_per_day = 1"
        ),
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    return {
        "JRP_VAULT_DIR": str(vault),
        "JRP_STORE_DIR": str(tmp_path / "store"),
        "JRP_DAILY_RESEARCH_CONFIG": str(cfg),
        "TYPESAFE_API_KEY": "replay",
        "DASHSCOPE_API_KEY": "replay",
    }


async def test_one_line_end_to_end(cassette: ClientFactory, env: dict[str, str]):
    http = cassette(fake_world())
    (outcome,) = await run_pipeline(env, now=b.T0, http=http, pacing=False)

    # Report note in the vault, named from slug and date only.
    note = Path(env["JRP_VAULT_DIR"]) / "daily-research" / "2026-09-22_jrp_akc.md"
    assert outcome.note == note
    text = note.read_text(encoding="utf-8")
    assert "category: jrp" in text and "## Claims" in text and "## 運用" in text
    assert "claude_calls: 0" in text
    claim_lines = [ln for ln in text.splitlines() if "jrp:claim:" in ln]
    assert claim_lines, text
    assert outcome.report.rendering == "prose"
    assert outcome.report.operations.jev_questions > 0
    assert outcome.report.operations.claude_calls == 0

    # The store holds the report and its claims; web_search skipped for lack of a key.
    part = GraphStore(Path(env["JRP_STORE_DIR"])).line("akc")
    assert isinstance(part.get(outcome.report.id), Report)
    assert any("web_search: key 未設定" in ln for ln in outcome.operations)

    # The author ticks the first claim ⭕; the next run's harvest turns it into a Label.
    note.write_text(
        text.replace(claim_lines[0], claim_lines[0].replace("- [ ] ", "- [x] ", 1)),
        encoding="utf-8",
    )
    (ticked_id,) = harvest_text(note.read_text(encoding="utf-8"))
    from jev_research_pipeline.pipeline.runner import harvest_line

    lines = harvest_line(
        GraphStore(Path(env["JRP_STORE_DIR"])), Path(env["JRP_VAULT_DIR"]), "akc", b.T0
    )
    assert lines[0] == f"harvest: label 1 件 / 取り消し {len(claim_lines) - 1} 件"
    labels = [n for n in part.load().values() if isinstance(n, Label)]
    assert [(lb.claim, lb.verdict) for lb in labels] == [(ticked_id, "correct")]


async def test_same_day_rerun_asks_jev_nothing_new(cassette: ClientFactory, env: dict[str, str]):
    http = cassette(fake_world())
    (first,) = await run_pipeline(env, now=b.T0, http=http, pacing=False)
    # Rewind the rotation so the same line runs again today.
    GraphStore(Path(env["JRP_STORE_DIR"])).pipeline().remove(
        [n.id for n in GraphStore(Path(env["JRP_STORE_DIR"])).pipeline().load().values()]
    )
    (second,) = await run_pipeline(env, now=b.T0, http=http, pacing=False)
    assert second.report.id == first.report.id
    assert second.report.operations.jev_questions == 0


async def test_missing_vault_env_writes_nothing(cassette: ClientFactory, env: dict[str, str]):
    from jev_research_pipeline.report import VaultNotConfigured

    del env["JRP_VAULT_DIR"]
    with pytest.raises(VaultNotConfigured):
        await run_pipeline(env, now=b.T0, http=cassette(fake_world()), pacing=False)
