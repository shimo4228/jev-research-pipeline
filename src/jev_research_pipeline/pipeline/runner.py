"""`jrp run`: harvest ticks first, then the next lines in rotation, one report each.

Environment (nothing is guessed):
    JRP_VAULT_DIR          vault root (required; nothing is written without it)
    JRP_STORE_DIR          pipeline store root (default ./var/store)
    TYPESAFE_API_KEY       Jev key (required)
    DASHSCOPE_API_KEY      Qwen key (required)
    TAVILY_API_KEY         optional; web_search is skipped without it
    GITHUB_TOKEN           optional; raises the GitHub search limit
    JRP_COST_CAP_USD       optional cost cap per line-run → partial report
    JRP_JEV_USD_PER_QUESTION  optional Jev price for the cost meter
    JRP_DAILY_RESEARCH_CONFIG  optional config.toml path
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.model import Report
from jev_research_pipeline.report import harvest_note, note_report_id, report_notes, vault_dir
from jev_research_pipeline.store import GraphStore, advance_rotation

from .config import config_path, line_context, load_tracks, rotation_config
from .run import Keys, LineOutcome, LineRun

STORE_ENV: Final = "JRP_STORE_DIR"
DEFAULT_STORE: Final = Path("var/store")
KEY_ENVS: Final = ("TYPESAFE_API_KEY", "DASHSCOPE_API_KEY")


class MissingKey(RuntimeError):
    pass


def store_dir(env: Mapping[str, str]) -> Path:
    raw = env.get(STORE_ENV)
    return Path(raw) if raw else DEFAULT_STORE


def keys(env: Mapping[str, str]) -> Keys:
    missing = [k for k in KEY_ENVS if not env.get(k)]
    if missing:
        raise MissingKey(f"missing env: {', '.join(missing)}")
    return Keys(typesafe=env["TYPESAFE_API_KEY"], dashscope=env["DASHSCOPE_API_KEY"])


def harvest_line(store: GraphStore, vault: Path, slug: str, now: AwareDatetime) -> list[str]:
    """Labels from every jrp note of the line into its partition (decision 5)."""
    part = store.line(slug)
    reports = {n.id: n for n in part.load().values() if isinstance(n, Report)}
    labels = withdrawn = 0
    skipped: list[str] = []
    for note in report_notes(vault, slug):
        report = reports.get(note_report_id(note) or "")
        if report is None:
            skipped.append(f"{note.name}: unknown_report")
            continue
        result = harvest_note(note, now=now, report_claims=frozenset(report.claims))
        if result.skipped is not None:
            skipped.append(f"{note.name}: {result.skipped}")
            continue
        part.put(result.labels)
        part.remove(result.cleared)
        labels += len(result.labels)
        withdrawn += len(result.cleared)
    lines = [f"harvest: label {labels} 件 / 取り消し {withdrawn} 件"]
    return lines + [f"harvest skip: {s}" for s in skipped]


def lines_per_day(config: Path) -> int:
    general = tomllib.loads(config.read_text(encoding="utf-8")).get("general", {})
    return int(general.get("lines_per_day", 3))


async def run_pipeline(
    env: Mapping[str, str], *, now: AwareDatetime, http: httpx2.AsyncClient, pacing: bool = True
) -> list[LineOutcome]:
    vault = vault_dir(env)
    api_keys = keys(env)
    cfg = config_path(env)
    tracks = {t.slug: t for t in load_tracks(cfg)}
    rotation = rotation_config(list(tracks.values()), per_tick=lines_per_day(cfg))
    store = GraphStore(store_dir(env))
    harvested = {slug: harvest_line(store, vault, slug, now) for slug in rotation.order}
    outcomes: list[LineOutcome] = []
    for slug in advance_rotation(store, rotation, now):
        run = LineRun(
            ctx=line_context(tracks[slug]),
            partition=store.line(slug),
            index_path=store.root / "index" / f"{slug}.sqlite",
            vault=vault,
            http=http,
            keys=api_keys,
            env=env,
            now=now,
            harvest_notes=harvested[slug],
            pacing=pacing,
        )
        outcomes.append(await run.execute())
    return outcomes
