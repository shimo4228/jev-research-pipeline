"""Step 10: lines from daily-research config.toml, vocabulary from each line's graph.jsonld."""

import json
from pathlib import Path

import pytest

from jev_research_pipeline.pipeline.config import (
    line_context,
    load_tracks,
    rotation_config,
)

CONFIG = """
[general]
lines_per_day = 3

[tracks.akc]
name = "Agent Knowledge Cycle 前進"
focus = "x"

[[tracks.akc.repos]]
key = "akc"
target_repo = "{repo_akc}"
target_doi = "10.5281/zenodo.21644565"

[tracks.edge]
name = "Edge 探索"
focus = "y"

[[tracks.edge.repos]]
key = "edge"
target_repo = "{repo_edge}"

[tracks.jev]
name = "Jev エコシステム観測"
mode = "ecosystem"
daily = true
focus = "z"
"""

GRAPH = {
    "@context": {"@vocab": "https://schema.org/"},
    "@graph": [
        {
            "@id": "https://doi.org/10.5281/zenodo.19200726",
            "@type": ["ResearchLine", "ScholarlyArticle"],
            "name": "Agent Knowledge Cycle",
            "url": "https://github.com/shimo4228/agent-knowledge-cycle",
        },
        {
            "@id": "https://doi.org/10.5281/zenodo.19212118",
            "@type": ["ResearchLine", "ScholarlyArticle"],
            "name": "Contemplative Agent",
            "url": "https://github.com/shimo4228/contemplative-agent",
        },
        {
            "@id": "https://shimo4228.github.io/shimo4228/vocab#concept/six-phase-loop",
            "@type": "Concept",
            "name": "six-phase loop",
            "alternateName": [
                {"@value": "six-phase loop", "@language": "en"},
                {"@value": "6 フェーズループ", "@language": "ja"},
            ],
        },
        {
            "@id": "https://x/concept/b",
            "@type": ["Concept"],
            "name": "scaffold dissolution",
            "alternateName": "SD",
        },
        {"@id": "https://x/term/c", "@type": "DefinedTerm", "name": "not a concept"},
    ],
}


@pytest.fixture
def world(tmp_path: Path) -> Path:
    akc = tmp_path / "agent-knowledge-cycle"
    akc.mkdir()
    (akc / "graph.jsonld").write_text(json.dumps(GRAPH), encoding="utf-8")
    edge = tmp_path / "edge-frontier"
    edge.mkdir()  # no graph.jsonld
    cfg = tmp_path / "config.toml"
    cfg.write_text(CONFIG.format(repo_akc=akc, repo_edge=edge), encoding="utf-8")
    return cfg


def test_tracks_keep_config_order_and_flags(world: Path):
    tracks = load_tracks(world)
    assert [t.slug for t in tracks] == ["akc", "edge", "jev"]
    assert [t.daily for t in tracks] == [False, False, True]
    assert tracks[2].repo is None


def test_rotation_skips_daily_and_repo_less_tracks(world: Path):
    config = rotation_config(load_tracks(world), per_tick=3)
    assert config.order == ("akc", "edge")
    assert config.per_tick == 3


def test_line_id_is_the_graph_research_line_for_this_repo(world: Path):
    akc = load_tracks(world)[0]
    ctx = line_context(akc)
    assert ctx.line.id == "https://doi.org/10.5281/zenodo.19200726"  # byte-identical
    assert ctx.line.slug == "akc"
    assert ctx.line.name == "Agent Knowledge Cycle 前進"
    assert ctx.vocabulary == ("six-phase loop", "6 フェーズループ", "scaffold dissolution", "SD")


def test_line_without_graph_falls_back_to_repo_url_and_name(world: Path):
    edge = load_tracks(world)[1]
    ctx = line_context(edge)
    assert ctx.line.id == "https://github.com/shimo4228/edge-frontier"
    assert ctx.vocabulary == ("Edge 探索",)


def test_graph_is_only_read(world: Path):
    akc = load_tracks(world)[0]
    graph = akc.repo / "graph.jsonld" if akc.repo else None
    assert graph is not None
    before = graph.read_bytes()
    line_context(akc)
    assert graph.read_bytes() == before


def test_target_repo_tilde_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / "c.toml"
    cfg.write_text(
        '[tracks.akc]\nname = "A"\n[[tracks.akc.repos]]\ntarget_repo = "~/repo"\n', encoding="utf-8"
    )
    (track,) = load_tracks(cfg)
    assert track.repo == tmp_path / "repo"
