"""Lines and their vocabulary, read from the existing daily-research setup (decision 2).

- Line list: `[tracks.<slug>]` of the config.toml, in file order. Rotation uses every
  track that is not `daily = true` (a daily track runs on every tick beside it); a track
  needs no repo (plan productize-en-zh P2: graph.jsonld is an optional vocabulary source).
  Config path: env JRP_DAILY_RESEARCH_CONFIG, else ~/.config/jrp/config.toml (`jrp init`).
- Line @id, first that applies: the track's own `id`; the ResearchLine node in
  `<target_repo>/graph.jsonld` whose `url` points at that repo — reused byte-identically
  (decision 3); with env JRP_GITHUB_OWNER, github.com/<owner>/<repo name> (or
  github.com/<owner> for a track with no repo — the ids the author's store was built on);
  else `<STORE_NS>line/<slug>`. Without a graph the track name is the only vocabulary term.
- Vocabulary: `name` + every `alternateName` value of the graph's Concept and
  DefinedTerm nodes. `@type` is matched by its last segment, so the `ans:` / `schema:`
  prefixes the real graphs use are not dropped (second live run, 2026-09-23).
Both files are only read; nothing is ever written back (decision 2, non-goal).
"""

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pydantic import JsonValue

from jev_research_pipeline.home import JRP_HOME
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import STORE_NS, AdapterKind, Line
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.store import RotationConfig

CONFIG_ENV: Final = "JRP_DAILY_RESEARCH_CONFIG"
DEFAULT_CONFIG: Final = JRP_HOME / "config.toml"
OWNER_ENV: Final = "JRP_GITHUB_OWNER"
ADAPTERS: Final[tuple[AdapterKind, ...]] = ("arxiv", "hf_papers", "github", "web_search")
"""Fixed in code for every line (decision 4); the model never chooses sources."""


class TrackSpec(Value):
    slug: str
    name: str
    repo: Path | None
    daily: bool
    id: str | None = None
    """`[tracks.<slug>] id`: the line's @id as given, ahead of any derived one."""
    owner: str | None = None
    """JRP_GITHUB_OWNER: derive @ids from github.com/<owner> (the author's store)."""


def config_path(env: Mapping[str, str]) -> Path:
    raw = env.get(CONFIG_ENV)
    return Path(raw) if raw else DEFAULT_CONFIG


def load_tracks(path: Path, *, owner: str | None = None) -> list[TrackSpec]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tracks: dict[str, Any] = data.get("tracks", {})
    out: list[TrackSpec] = []
    for slug, spec in tracks.items():
        repos: list[dict[str, Any]] = spec.get("repos", [])
        repo = Path(str(repos[0]["target_repo"])).expanduser() if repos else None
        out.append(
            TrackSpec(
                slug=slug,
                name=str(spec["name"]),
                repo=repo,
                daily=bool(spec.get("daily", False)),
                id=str(spec["id"]) if spec.get("id") else None,
                owner=owner,
            )
        )
    return out


def env_tracks(env: Mapping[str, str]) -> list[TrackSpec]:
    """The configured tracks with this environment's id scheme (JRP_GITHUB_OWNER)."""
    return load_tracks(config_path(env), owner=env.get(OWNER_ENV) or None)


def rotation_config(tracks: list[TrackSpec], *, per_tick: int) -> RotationConfig:
    return RotationConfig(order=tuple(t.slug for t in tracks if not t.daily), per_tick=per_tick)


def _has_type(node: Mapping[str, JsonValue], *names: str) -> bool:
    """@type matched by its last segment: the real graphs write `ans:Concept` and
    `schema:DefinedTerm`, and a full IRI is equally valid JSON-LD. A single string and a
    list are both allowed by the spec, so both are handled."""
    t = node.get("@type")
    raw = [str(x) for x in t] if isinstance(t, list) else [str(t)]
    suffixes = {v.replace("#", "/").replace(":", "/").rsplit("/", 1)[-1] for v in raw}
    return bool(suffixes & set(names))


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
    line_id = f"{STORE_NS}line/{track.slug}"
    if track.owner:
        line_id = f"https://github.com/{track.owner}" + (f"/{repo.name}" if repo else "")
    for n in nodes:
        url = n.get("url")
        if (
            repo
            and _has_type(n, "ResearchLine")
            and isinstance(url, str)
            and url.rstrip("/").endswith("/" + repo.name)
        ):
            line_id = str(n["@id"])
            break
    line_id = track.id or line_id
    vocab: list[str] = []
    for n in nodes:
        if _has_type(n, "Concept", "DefinedTerm"):
            vocab += _values(n.get("name")) + _values(n.get("alternateName"))
    vocabulary = tuple(dict.fromkeys(v.strip() for v in vocab if v.strip())) or (track.name,)
    line = Line(id=line_id, slug=track.slug, name=track.name, adapters=ADAPTERS)
    return LineContext(line=line, vocabulary=vocabulary)
