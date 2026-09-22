"""Lines and their vocabulary, read from the existing daily-research setup (decision 2).

- Line list: `[tracks.<slug>]` of daily-research's config.toml, in file order. Rotation
  uses the tracks that have a repo and are not `daily = true` (the daily jev track stays
  with the old pipeline). Config path: env JRP_DAILY_RESEARCH_CONFIG, else the default.
- Line @id: the ResearchLine node in `<target_repo>/graph.jsonld` whose `url` points at
  that repo — reused byte-identically (decision 3). Without a graph.jsonld the repo URL
  under GITHUB_OWNER is the id and the track name is the only vocabulary term.
- Vocabulary: `name` + every `alternateName` value of the graph's Concept nodes.
Both files are only read; nothing is ever written back (decision 2, non-goal).
"""

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pydantic import JsonValue

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import AdapterKind, Line
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.store import RotationConfig

CONFIG_ENV: Final = "JRP_DAILY_RESEARCH_CONFIG"
DEFAULT_CONFIG: Final = Path.home() / "MyAI_Lab" / "daily-research" / "config.toml"
GITHUB_OWNER: Final = "shimo4228"
ADAPTERS: Final[tuple[AdapterKind, ...]] = ("arxiv", "hf_papers", "github", "web_search")
"""Fixed in code for every line (decision 4); the model never chooses sources."""


class TrackSpec(Value):
    slug: str
    name: str
    repo: Path | None
    daily: bool


def config_path(env: Mapping[str, str]) -> Path:
    raw = env.get(CONFIG_ENV)
    return Path(raw) if raw else DEFAULT_CONFIG


def load_tracks(path: Path) -> list[TrackSpec]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tracks: dict[str, Any] = data.get("tracks", {})
    out: list[TrackSpec] = []
    for slug, spec in tracks.items():
        repos: list[dict[str, Any]] = spec.get("repos", [])
        repo = Path(str(repos[0]["target_repo"])).expanduser() if repos else None
        out.append(
            TrackSpec(
                slug=slug, name=str(spec["name"]), repo=repo, daily=bool(spec.get("daily", False))
            )
        )
    return out


def rotation_config(tracks: list[TrackSpec], *, per_tick: int) -> RotationConfig:
    return RotationConfig(
        order=tuple(t.slug for t in tracks if t.repo is not None and not t.daily), per_tick=per_tick
    )


def _types(node: Mapping[str, JsonValue]) -> list[str]:
    t = node.get("@type")
    return [str(x) for x in t] if isinstance(t, list) else [str(t)]


def _values(v: JsonValue) -> list[str]:
    """alternateName may be a string, a {@value} object, or a list of either."""
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        inner = v.get("@value")
        return [inner] if isinstance(inner, str) else []
    if isinstance(v, list):
        return [s for item in v for s in _values(item)]
    return []


def _read_graph(repo: Path) -> list[Mapping[str, JsonValue]]:
    path = repo / "graph.jsonld"
    if not path.is_file():
        return []
    graph = json.loads(path.read_text(encoding="utf-8")).get("@graph", [])
    return [n for n in graph if isinstance(n, dict)]


def line_context(track: TrackSpec) -> LineContext:
    repo = track.repo
    nodes = _read_graph(repo) if repo else []
    line_id = (
        f"https://github.com/{GITHUB_OWNER}/{repo.name}"
        if repo
        else f"https://github.com/{GITHUB_OWNER}"
    )
    for n in nodes:
        url = n.get("url")
        if (
            repo
            and "ResearchLine" in _types(n)
            and isinstance(url, str)
            and url.rstrip("/").endswith("/" + repo.name)
        ):
            line_id = str(n["@id"])
            break
    vocab: list[str] = []
    for n in nodes:
        if "Concept" in _types(n):
            vocab += _values(n.get("name")) + _values(n.get("alternateName"))
    vocabulary = tuple(dict.fromkeys(v.strip() for v in vocab if v.strip())) or (track.name,)
    line = Line(id=line_id, slug=track.slug, name=track.name, adapters=ADAPTERS)
    return LineContext(line=line, vocabulary=vocabulary)
