"""`jrp` — the pipeline's only entry point (launchd calls `jrp run` / `jrp drift`).

jrp run            harvest, then the next lines in rotation (env: pipeline.runner)
jrp fit            threshold proposals per line → <store>/proposals/<slug>/ (not applied)
jrp export-cases   labeled claims → <store>/cases/<slug>.yaml (pydantic-evals)
jrp drift          replay recorded Jev inputs live; needs JRP_DRIFT_LIVE=1
jrp migrate        bring the store up to today's schema; --dry-run prints the plan only

A store file from an older build stops every command with one line (store.migrate):
additive differences are migrated in place first, incompatible ones need `jrp migrate`.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import httpx2

from .adapters.routing import run_client
from .pipeline.config import config_path, line_context, load_tracks, rotation_config
from .pipeline.drift import LIVE_ENV, drift_table, drift_with_failures
from .pipeline.notify import notify
from .pipeline.runner import run_pipeline, store_dir
from .quality import agreement, trusted_axes
from .reduction import DecisionLog, export_cases, fit_thresholds, write_proposal
from .store import GraphStore
from .store.migrate import StoreSchemaError, migrate_store, prepare_store
from .telemetry import setup_telemetry

HTTP_TIMEOUT_S = 30.0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jrp")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("fit")
    sub.add_parser("export-cases")
    d = sub.add_parser("drift")
    d.add_argument("--cassettes", default="tests/cassettes/live", help="dir of live cassettes")
    m = sub.add_parser("migrate")
    m.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    return p


def _slugs(env: Mapping[str, str]) -> list[str]:
    return list(rotation_config(load_tracks(config_path(env)), per_tick=1).order)


async def _run(env: Mapping[str, str]) -> int:
    unanswered: list[str] = []
    try:
        async with run_client(timeout=HTTP_TIMEOUT_S) as http:
            outcomes = await run_pipeline(
                env, now=datetime.now().astimezone(), http=http, unanswered=unanswered
            )
    except Exception as e:
        # An unattended run that fails must not be silent (the log alone is not read).
        notify("jrp run FAILED", f"{type(e).__name__}: {e}", env=env)
        raise
    summary = ", ".join(
        f"{o.report.run_date} {o.note.stem}: {len(o.report.claims)} claims" for o in outcomes
    )
    # A line skipped for having no open question is the author's to fix, so it is said
    # out loud rather than looking like a quiet success.
    skipped = "; ".join(unanswered)
    sys.stdout.write("\n".join(filter(None, [summary, skipped])) + "\n")
    notify("jrp run", "; ".join(filter(None, [summary or "no line ran", skipped])), env=env)
    return 0


def _migrate(env: Mapping[str, str], *, dry_run: bool) -> int:
    lines = migrate_store(store_dir(env), dry_run=dry_run, today=datetime.now().astimezone().date())
    sys.stdout.write("\n".join(lines or ["store は現行 schema"]) + "\n")
    return 0


def _fit(env: Mapping[str, str]) -> int:
    store = GraphStore(store_dir(env))
    for slug in _slugs(env):
        log = DecisionLog.from_partition(store.line(slug))
        trusted = trusted_axes(agreement(log.judgments, log.labels))
        proposals = fit_thresholds(log, trusted=trusted)
        path = write_proposal(
            store.root / "proposals" / slug, proposals, day=datetime.now().astimezone().date()
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
        rows, failed = await drift_with_failures(
            sorted(cassettes.glob("*.json")), http, api_key=env["TYPESAFE_API_KEY"]
        )
    sys.stdout.write(drift_table(rows))
    worst = max((r.delta for r in rows), default=0.0)
    notify(
        "jrp drift",
        f"{len(rows)} answers compared, max Δp {worst:.3f}, {failed} replays failed",
        env=env,
    )
    return 1 if failed and not rows else 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    env = dict(os.environ)
    setup_telemetry(env)  # no OTEL_EXPORTER_OTLP_ENDPOINT → no SDK, no-op spans
    try:
        match args.command:
            case "run":
                return asyncio.run(_run(env))  # run_pipeline prepares the store itself
            case "fit":
                _prepared(env)
                return _fit(env)
            case "export-cases":
                _prepared(env)
                return _export(env)
            case "migrate":
                return _migrate(env, dry_run=bool(args.dry_run))
            case _:
                return asyncio.run(_drift(env, Path(args.cassettes)))
    except StoreSchemaError as e:
        sys.stderr.write(f"{e}\n")
        if args.command == "run":
            notify("jrp run STOPPED", str(e), env=env)
        return 2


def _prepared(env: Mapping[str, str]) -> None:
    for note in prepare_store(store_dir(env)):
        sys.stdout.write(f"{note}\n")
