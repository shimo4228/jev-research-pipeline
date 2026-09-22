"""End-to-end (Step 10): one line through a tmp vault on cassette replay, then a tick
edited in the note becomes a Label on the next run's harvest."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2
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
    assert second.report.claims == first.report.claims  # not emptied by the re-run
    assert second.report.rendering == first.report.rendering
    assert second.report.operations.jev_questions == 0
    assert second.report.operations.generation_output_tokens == 0  # Qwen not asked again


async def test_missing_vault_env_writes_nothing(cassette: ClientFactory, env: dict[str, str]):
    from jev_research_pipeline.report import VaultNotConfigured

    del env["JRP_VAULT_DIR"]
    with pytest.raises(VaultNotConfigured):
        await run_pipeline(env, now=b.T0, http=cassette(fake_world()), pacing=False)


async def test_cost_cap_zero_gives_partial_report(cassette: ClientFactory, env: dict[str, str]):
    env["JRP_COST_CAP_USD"] = "0"
    env["JRP_JEV_USD_PER_QUESTION"] = "0.001"
    (outcome,) = await run_pipeline(env, now=b.T0, http=cassette(fake_world()), pacing=False)
    # The cap is checked between steps: the first spend trips it, the rest is skipped.
    assert outcome.report.partial
    assert outcome.report.claims == ()
    assert outcome.report.rendering == "template"


async def test_note_date_follows_the_local_timezone(cassette: ClientFactory, env: dict[str, str]):
    # First live run: 06:31 JST wrote a 2026-09-22 note because `now` was UTC.
    jst = datetime(2026, 9, 23, 6, 31, tzinfo=ZoneInfo("Asia/Tokyo"))
    (outcome,) = await run_pipeline(env, now=jst, http=cassette(fake_world()), pacing=False)
    assert outcome.note.name == "2026-09-23_jrp_akc.md"
    assert outcome.report.run_date.isoformat() == "2026-09-23"


def test_cli_uses_a_local_aware_now():
    import inspect

    from jev_research_pipeline import cli

    source = inspect.getsource(cli._run)  # pyright: ignore[reportPrivateUsage]
    assert "datetime.now().astimezone()" in source
    assert "datetime.now(UTC)" not in source


async def test_operations_show_prose_time_and_failure(cassette: ClientFactory, env: dict[str, str]):
    """The first live run's 30s timeout left no trace in the report."""

    async def no_prose(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "dashscope-intl.aliyuncs.com":
            model = json.loads(request.content)["model"]
            if model == "qwen3.8-max":
                return httpx2.Response(400, json={"error": {"message": "Request timed out"}})
        return await fake_world()(request)

    (outcome,) = await run_pipeline(env, now=b.T0, http=cassette(no_prose), pacing=False)
    assert outcome.report.rendering == "template"
    prose_lines = [ln for ln in outcome.operations if ln.startswith("prose 第")]
    assert prose_lines and "失敗" in prose_lines[0]
    assert "s" in prose_lines[0].rsplit(" ", 1)[1]
    assert any("prose 第" in ln for ln in outcome.note.read_text(encoding="utf-8").splitlines())
