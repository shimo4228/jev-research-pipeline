"""`jrp` — the pipeline's only entry point (launchd calls `jrp run` / `jrp drift`).

jrp run            harvest, then the next lines in rotation (env: pipeline.runner)
jrp fit            threshold proposals per line → <store>/proposals/<slug>/ (not applied)
jrp export-cases   labeled claims → <store>/cases/<slug>.yaml (pydantic-evals)
jrp drift          replay recorded Jev inputs live; needs JRP_DRIFT_LIVE=1
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx2

from .pipeline.config import config_path, line_context, load_tracks, rotation_config
from .pipeline.drift import LIVE_ENV, drift, drift_table
from .pipeline.notify import notify
from .pipeline.runner import run_pipeline, store_dir
from .quality import agreement, trusted_axes
from .reduction import DecisionLog, export_cases, fit_thresholds, write_proposal
from .store import GraphStore

HTTP_TIMEOUT_S = 30.0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jrp")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("fit")
    sub.add_parser("export-cases")
    d = sub.add_parser("drift")
    d.add_argument("--cassettes", default="tests/cassettes/live", help="dir of live cassettes")
    return p


def _slugs(env: Mapping[str, str]) -> list[str]:
    return list(rotation_config(load_tracks(config_path(env)), per_tick=1).order)


async def _run(env: Mapping[str, str]) -> int:
    async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
        outcomes = await run_pipeline(env, now=datetime.now(UTC), http=http)
    summary = ", ".join(
        f"{o.report.run_date} {o.note.stem}: {len(o.report.claims)} claims" for o in outcomes
    )
    sys.stdout.write(summary + "\n")
    notify("jrp run", summary or "no line ran", env=env)
    return 0


def _fit(env: Mapping[str, str]) -> int:
    store = GraphStore(store_dir(env))
    for slug in _slugs(env):
        log = DecisionLog.from_partition(store.line(slug))
        trusted = trusted_axes(agreement(log.judgments, log.labels))
        proposals = fit_thresholds(log, trusted=trusted)
        path = write_proposal(
            store.root / "proposals" / slug, proposals, day=datetime.now(UTC).date()
        )
        sys.stdout.write(f"{slug}: {len(proposals)} proposals → {path}\n")
    return 0


def _export(env: Mapping[str, str]) -> int:
    store = GraphStore(store_dir(env))
    tracks = {t.slug: t for t in load_tracks(config_path(env))}
    for slug in _slugs(env):
        log = DecisionLog.from_partition(store.line(slug))
        path = export_cases(log, line_context(tracks[slug]), store.root / "cases" / f"{slug}.yaml")
        sys.stdout.write(f"{slug}: {len(log.gold())} cases → {path}\n")
    return 0


async def _drift(env: Mapping[str, str], cassettes: Path) -> int:
    if env.get(LIVE_ENV) != "1" or not env.get("TYPESAFE_API_KEY"):
        sys.stderr.write(f"drift calls the live API: set {LIVE_ENV}=1 and TYPESAFE_API_KEY\n")
        return 2
    async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
        rows = await drift(sorted(cassettes.glob("*.json")), http, api_key=env["TYPESAFE_API_KEY"])
    table = drift_table(rows)
    sys.stdout.write(table)
    worst = max((r.delta for r in rows), default=0.0)
    notify("jrp drift", f"{len(rows)} answers compared, max Δp {worst:.3f}", env=env)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    env = dict(os.environ)
    match args.command:
        case "run":
            return asyncio.run(_run(env))
        case "fit":
            return _fit(env)
        case "export-cases":
            return _export(env)
        case _:
            return asyncio.run(_drift(env, Path(args.cassettes)))
