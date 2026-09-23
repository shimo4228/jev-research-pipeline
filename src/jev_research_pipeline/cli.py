"""`jrp` — the pipeline's only entry point (launchd calls `jrp run` / `jrp drift`).

jrp run            harvest, then the next lines in rotation (env: pipeline.runner)
jrp fit            threshold proposals per line → <store>/proposals/<slug>/ (not applied)
jrp export-cases   labeled claims → <store>/cases/<slug>.yaml (pydantic-evals)
jrp drift          replay recorded Jev inputs live; needs JRP_DRIFT_LIVE=1
jrp migrate        bring the store up to today's schema; --dry-run prints the plan only
jrp queries check --line <slug>
                   send each authored query once, print hits (pipeline.query_check)
jrp prose export|bench|read|gate
                   the prose bench: frozen inputs, variants, the author's blind reading file,
                   the fidelity judge's gate files (pipeline.prose_bench)

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
from .pipeline import prose_bench as pb
from .pipeline.concurrency import prose_concurrency
from .pipeline.config import config_path, line_context, load_tracks, rotation_config
from .pipeline.drift import LIVE_ENV, drift_table, drift_with_failures
from .pipeline.notify import notify
from .pipeline.query_check import check_queries
from .pipeline.runner import run_pipeline, store_dir
from .quality import agreement, trusted_axes
from .questions import NoQuestions
from .qwen.prose import INSTRUCTIONS
from .reduction import DecisionLog, export_cases, fit_thresholds, write_proposal
from .store import GraphStore
from .store.migrate import StoreSchemaError, migrate_store, prepare_store
from .telemetry import setup_telemetry

HTTP_TIMEOUT_S = 30.0
RUBRIC = Path(__file__).resolve().parents[2] / "docs" / "prose-rubric.md"
"""The fidelity judge's checks; each gate file embeds them (pipeline.prose_bench.gate_files)."""


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
    q = sub.add_parser("queries")
    q.add_argument("action", choices=["check"])
    q.add_argument("--line", required=True, help="line slug (config.toml track)")
    pr = sub.add_parser("prose")
    pr.add_argument("action", choices=["export", "bench", "read", "gate"])
    pr.add_argument("--from", dest="roots", action="append", default=[], help="extra store root")
    pr.add_argument("--variant", help="bench: variant name (drafts/<name>/)")
    pr.add_argument("--prompt", help="bench: instructions file; omitted = the run's prompt")
    pr.add_argument("--model", default="qwen3.8-max")
    pr.add_argument("--no-thinking", action="store_true")
    pr.add_argument("--sources", action="store_true", help="bench: send source excerpts")
    pr.add_argument("--check", help="bench: self-check instructions file (second pass)")
    pr.add_argument("--cases", help="bench/read/gate: comma-separated case ids (default all)")
    pr.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    pr.add_argument("--variants", help="read: comma-separated variants to show side by side")
    pr.add_argument("--out", help="read: the reading file to write")
    pr.add_argument("--verdicts", help="gate: summarize the judge's verdict dir instead")
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
                return asyncio.run(_async_command(env, args))
    except StoreSchemaError as e:
        sys.stderr.write(f"{e}\n")
        if args.command == "run":
            notify("jrp run STOPPED", str(e), env=env)
        return 2


async def _async_command(env: Mapping[str, str], args: argparse.Namespace) -> int:
    if args.command == "queries":
        return await _check_queries(env, str(args.line))
    if args.command == "prose":
        return await _prose(env, args)
    return await _drift(env, Path(args.cassettes))


def _ids(raw: str | None) -> set[str] | None:
    return {x.strip() for x in raw.split(",") if x.strip()} if raw else None


async def _prose(env: Mapping[str, str], args: argparse.Namespace) -> int:
    root = store_dir(env)
    bench = pb.bench_dir(root)
    # named cases are taken as named, whichever split they sit in (the default split is dev,
    # and a holdout id under it used to select nothing without a word: code review)
    split = "all" if args.cases else args.split
    match args.action:
        case "export":
            tracks = load_tracks(config_path(env))
            contexts = {t.slug: line_context(t) for t in tracks}
            roots = [root, *(Path(r) for r in args.roots)]
            cases = pb.export(roots, contexts, bench)
            held = sum(1 for c in cases if c.split == "holdout")
            lines = [f"{len(cases)} cases ({held} holdout) → {bench / 'cases'}"]
        case "bench":
            instructions = (
                Path(args.prompt).read_text(encoding="utf-8") if args.prompt else INSTRUCTIONS
            )
            variant = pb.Variant(
                name=str(args.variant),
                instructions=instructions,
                model=str(args.model),
                thinking=not args.no_thinking,
                sources=bool(args.sources),
                check=Path(args.check).read_text(encoding="utf-8") if args.check else None,
            )
            async with run_client(timeout=pb.PROSE_TIMEOUT_S) as http:
                lines = await pb.run_bench(
                    bench,
                    variant,
                    http=http,
                    api_key=env["DASHSCOPE_API_KEY"],
                    split=split,
                    concurrency=prose_concurrency(env),
                    only=_ids(args.cases),
                )
        case "read":
            out, n = pb.read_file(
                bench,
                [v for v in str(args.variants).split(",") if v],
                Path(args.out),
                split=split,
                only=_ids(args.cases),
            )
            if not n:
                sys.stderr.write("no case has a draft from every variant given\n")
                return 1
            lines = [f"reading file → {out}, {n} cases (key: {out.with_suffix('.key.json')})"]
        case _:
            if args.verdicts:
                lines = pb.gate_summary(bench, str(args.variant), Path(args.verdicts))
            else:
                rubric = RUBRIC.read_text(encoding="utf-8")
                out, n = pb.gate_files(
                    bench, str(args.variant), rubric, split=split, only=_ids(args.cases)
                )
                if not n:
                    sys.stderr.write(f"no draft of {args.variant} in the selected cases\n")
                    return 1
                lines = [f"gate files → {out}, {n} drafts"]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


async def _check_queries(env: Mapping[str, str], slug: str) -> int:
    try:
        async with run_client(timeout=HTTP_TIMEOUT_S) as http:
            lines = await check_queries(env, slug, http=http, now=datetime.now().astimezone())
    except NoQuestions as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def _prepared(env: Mapping[str, str]) -> None:
    for note in prepare_store(store_dir(env)):
        sys.stdout.write(f"{note}\n")
