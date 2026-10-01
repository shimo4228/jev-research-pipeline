"""`jrp` — the pipeline's only entry point (launchd calls `jrp run` / `jrp drift`).

jrp run            harvest, then the next lines in rotation (env: pipeline.runner)
jrp doctor         check what a run needs (env, config, questions, keys, the writer's login)
                   without running one; non-zero exit on a failure (pipeline.doctor)
jrp init           write ~/.config/jrp/{env,config.toml,questions/} where missing (init)
jrp try --line <slug>
                   one line, once, into a scratch store and vault; prints the note (init)
jrp schedule install [--hour H --minute M]
                   write a launchd job for the daily run under ~/.config/jrp/launchd/ and
                   print how to load it; never loads it (scheduling)
jrp notify <title> <body>
                   one message to the configured channels (pipeline.notify)
jrp questions new --line <slug>
                   a Claude Code session that writes the line's questions (skill jrp-question)
jrp fit            threshold proposals per line → <store>/proposals/<slug>/ (not applied)
jrp export-cases   labeled claims → <store>/cases/<slug>.yaml (pydantic-evals)
jrp drift          replay recorded Jev inputs live; needs JRP_DRIFT_LIVE=1
jrp migrate        bring the store up to today's schema; --dry-run prints the plan only
jrp queries check --line <slug>
                   send each authored query once, print hits (pipeline.query_check)
jrp prose export|bench|read|gate
                   the prose bench: frozen inputs, variants, the author's blind reading file,
                   the fidelity judge's gate files (pipeline.prose_bench)
jrp codex login    sign in to the ChatGPT/Codex subscription once, for the default prose
                   model (generation.codex)

A store file from an older build stops every command with one line (store.migrate):
additive differences are migrated in place first, incompatible ones need `jrp migrate`.
"""

import argparse
import asyncio
import os
import shutil
import signal
import subprocess
import sys
import webbrowser
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Final

import httpx2

from .generation import (
    MissingCredentials,
    ModelSpecError,
    Writer,
    parse_model,
    prose_auth,
    prose_model_spec,
)
from .generation.claude_code import CLAUDE_BIN_ENV, claude_bin
from .generation.codex import codex_auth_path, login
from .generation.prose import INSTRUCTIONS
from .init import init, init_lines, question_session, try_line
from .note_text import LANGS, NOTE_LANG_ENV, Lang, note_lang
from .pipeline import prose_bench as pb
from .pipeline import prose_eval
from .pipeline.concurrency import prose_concurrency
from .pipeline.config import config_path, env_tracks, line_context, rotation_config
from .pipeline.doctor import doctor
from .pipeline.drift import LIVE_ENV, drift_table, drift_with_failures
from .pipeline.notify import notify
from .pipeline.query_check import check_queries
from .pipeline.runner import run_pipeline, run_summary, store_dir
from .quality import agreement, trusted_axes
from .questions import NoQuestions, questions_path
from .reduction import DecisionLog, export_cases, fit_thresholds, write_proposal
from .scheduling import install, install_lines
from .store import GraphStore
from .store.migrate import StoreSchemaError, migrate_store, prepare_store
from .telemetry import setup_telemetry

HTTP_TIMEOUT_S = 30.0
DOCS = Path(__file__).resolve().parents[2] / "docs"
RUBRICS: Final[Mapping[Lang, Path]] = {
    "ja": DOCS / "prose-rubric.md",
    "en": DOCS / "prose-rubric.en.md",
    "zh": DOCS / "prose-rubric.zh.md",
}
"""The fidelity judge's checks per draft language; each gate file embeds the one of its
variant's language (pipeline.prose_bench.gate_files)."""


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jrp")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("doctor")
    i = sub.add_parser("init", help="write ~/.config/jrp/{env,config.toml,questions/} if missing")
    i.add_argument("--lang", choices=list(LANGS), default="en", help="the notes' language")
    sc = sub.add_parser("schedule", help="write a launchd job for the daily run (not loaded)")
    sc.add_argument("action", choices=["install"])
    sc.add_argument("--hour", type=int, default=5)
    sc.add_argument("--minute", type=int, default=0)
    no = sub.add_parser("notify", help="send one message to the configured channels")
    no.add_argument("title")
    no.add_argument("body")
    qn = sub.add_parser("questions", help="set up a line's questions with Claude Code")
    qn.add_argument("action", choices=["new"])
    qn.add_argument("--line", required=True, help="line slug (config.toml track)")
    t = sub.add_parser("try", help="run one line once into a scratch store and vault")
    t.add_argument("--line", required=True, help="line slug (config.toml track)")
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
    pr.add_argument(
        "action", choices=["export", "bench", "read", "gate", "judge", "comprehend", "scores"]
    )
    pr.add_argument("--from", dest="roots", action="append", default=[], help="extra store root")
    pr.add_argument("--variant", help="bench: variant name (drafts/<name>/)")
    pr.add_argument("--prompt", help="bench: instructions file; omitted = the run's prompt")
    pr.add_argument(
        "--model", help="bench: <backend>:<model>; omitted = the run's (JRP_PROSE_MODEL)"
    )
    pr.add_argument("--no-thinking", action="store_true")
    pr.add_argument("--sources", action="store_true", help="bench: send source excerpts")
    pr.add_argument("--check", help="bench: self-check instructions file (second pass)")
    pr.add_argument("--lang", choices=list(LANGS), default="ja", help="bench: the drafts' language")
    pr.add_argument("--cases", help="bench/read/gate: comma-separated case ids (default all)")
    pr.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    pr.add_argument("--variants", help="read/scores: comma-separated variants to show side by side")
    pr.add_argument("--out", help="read: the reading file to write")
    pr.add_argument("--verdicts", help="gate: summarize the judge's verdict dir instead")
    c = sub.add_parser("codex")
    c.add_argument("action", choices=["login"])
    return p


def _slugs(env: Mapping[str, str]) -> list[str]:
    return list(rotation_config(env_tracks(env), per_tick=1).order)


async def _run(env: Mapping[str, str]) -> int:
    unanswered: list[str] = []
    failed: list[str] = []
    # The launchd wrapper's watchdog stops a hung run with SIGTERM. Its default action ends
    # python without unwinding, which would orphan a claude-code CLI (it runs in a session of
    # its own, out of reach of the wrapper's group kill) to spend the plan unread. Cancelling
    # the run instead unwinds through generation.claude_code.run_claude, which kills it.
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if task is not None:
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
            outcomes = await run_pipeline(
                env,
                now=datetime.now().astimezone(),
                http=http,
                unanswered=unanswered,
                failed=failed,
            )
    except Exception as e:
        # An unattended run that fails must not be silent (the log alone is not read).
        notify("jrp run FAILED", f"{type(e).__name__}: {e}", env=env)
        raise
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
    # A skipped line (no open question) and a degraded one (failed drafts, a refused writer,
    # failed fetches, the cost cap) are said out loud rather than looking like a quiet
    # success; one message either way (runner.run_summary).
    title, body = run_summary(outcomes, skipped=unanswered, failed=failed)
    sys.stdout.write(f"{title}\n{body}\n")
    notify(title, body, env=env)
    return 0


def _init(lang: Lang) -> int:
    sys.stdout.write("\n".join(init_lines(init(lang=lang))) + "\n")
    return 0


async def _try(env: Mapping[str, str], slug: str) -> int:
    async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
        ran = await try_line(env, slug, http=http, now=datetime.now().astimezone())
    if ran is None:
        slugs = ", ".join(t.slug for t in env_tracks(env))
        sys.stderr.write(f"no line {slug!r} in {config_path(env)} (lines: {slugs})\n")
        return 1
    sys.stdout.write("\n".join(ran.lines) + "\n")
    return 0 if ran.notes else 1


def _schedule(hour: int, minute: int) -> int:
    if not (0 <= hour < 24 and 0 <= minute < 60):
        sys.stderr.write(f"not a time of day: {hour:02d}:{minute:02d}\n")
        return 1
    found = shutil.which("jrp")
    if found is None or ".venv" in Path(found).parts:
        # a checkout's venv goes with the checkout; the job must name a jrp that stays
        sys.stderr.write("install jrp first, so the job can name it: uv tool install <jrp>\n")
        return 1
    jrp = Path(found).resolve()
    sys.stdout.write("\n".join(install_lines(install(jrp=jrp, hour=hour, minute=minute))) + "\n")
    return 0


def _questions_new(env: Mapping[str, str], slug: str) -> int:
    """An interactive Claude Code session on the jrp-question procedure (init.question_session)."""
    slugs = [t.slug for t in env_tracks(env)]
    if slug not in slugs:
        sys.stderr.write(f"no line {slug!r} in {config_path(env)} (lines: {', '.join(slugs)})\n")
        return 1
    binary = claude_bin(env)
    if binary is None:
        sys.stderr.write(f"no Claude Code CLI: install it, or set {CLAUDE_BIN_ENV}\n")
        return 1
    argv = question_session(binary, slug, questions_path(env, slug))
    return subprocess.run(argv, check=False).returncode


def _doctor(env: Mapping[str, str]) -> int:
    checks = doctor(env)
    sys.stdout.write("".join(f"{c.line()}\n" for c in checks))
    return 0 if all(c.ok for c in checks) else 1


def _migrate(env: Mapping[str, str], *, dry_run: bool) -> int:
    lines = migrate_store(store_dir(env), dry_run=dry_run, today=datetime.now().astimezone().date())
    sys.stdout.write("\n".join(lines or ["store は現行 schema"]) + "\n")
    return 0


def _fit(env: Mapping[str, str]) -> int:
    store = GraphStore(store_dir(env))
    for slug in _slugs(env):
        log = DecisionLog.from_partition(store.line(slug))
        trusted = trusted_axes(agreement(log.judgments, log.labels))
        skipped: list[str] = []
        proposals = fit_thresholds(log, trusted=trusted, skipped=skipped)
        path = write_proposal(
            store.root / "proposals" / slug,
            proposals,
            day=datetime.now().astimezone().date(),
            skipped=skipped,
        )
        sys.stdout.write(f"{slug}: {len(proposals)} proposals → {path}\n")
        sys.stdout.write("".join(f"  提案なし {s}\n" for s in skipped))
    return 0


def _export(env: Mapping[str, str]) -> int:
    store = GraphStore(store_dir(env))
    tracks = {t.slug: t for t in env_tracks(env)}
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
            case "fit" | "export-cases":
                _prepared(env)
                return _fit(env) if args.command == "fit" else _export(env)
            case "migrate":
                return _migrate(env, dry_run=bool(args.dry_run))
            case "doctor":
                return _doctor(env)
            case _:
                return asyncio.run(_async_command(env, args))
    except StoreSchemaError as e:
        sys.stderr.write(f"{e}\n")
        if args.command == "run":
            notify("jrp run STOPPED", str(e), env=env)
        return 2


async def _async_command(env: Mapping[str, str], args: argparse.Namespace) -> int:
    match args.command:
        case "init":
            code = _init(note_lang({NOTE_LANG_ENV: str(args.lang)}))
        case "try":
            code = await _try(env, str(args.line))
        case "questions":
            code = _questions_new(env, str(args.line))
        case "schedule":
            code = _schedule(int(args.hour), int(args.minute))
        case "notify":
            code = 0 if notify(str(args.title), str(args.body), env=env) else 1
        case "queries":
            code = await _check_queries(env, str(args.line))
        case "prose":
            code = await _prose(env, args)
        case "codex":
            code = await _codex_login(env)
        case _:
            code = await _drift(env, Path(args.cassettes))
    return code


def _ids(raw: str | None) -> set[str] | None:
    return {x.strip() for x in raw.split(",") if x.strip()} if raw else None


async def _prose_eval(
    env: Mapping[str, str], args: argparse.Namespace, bench: Path
) -> list[str] | None:
    """`jrp prose judge|comprehend|scores`: the bench's claude -p judges (pipeline.prose_eval)."""
    if args.action == "scores":
        return prose_eval.scores_table(
            bench, [v for v in str(args.variants).split(",") if v], only=_ids(args.cases)
        )
    binary = claude_bin(env)
    if binary is None:
        sys.stderr.write(f"no Claude Code CLI: install it, or set {CLAUDE_BIN_ENV}\n")
        return None
    ask = prose_eval.claude_ask(binary)
    if args.action == "judge":
        lines = await prose_eval.judge(
            bench, str(args.variant), ask, concurrency=prose_concurrency(env)
        )
        return lines + pb.gate_summary(bench, str(args.variant))
    return await prose_eval.comprehend(
        bench, str(args.variant), ask, concurrency=prose_concurrency(env), only=_ids(args.cases)
    )


async def _prose(env: Mapping[str, str], args: argparse.Namespace) -> int:
    root = store_dir(env)
    bench = pb.bench_dir(root)
    # named cases are taken as named, whichever split they sit in (the default split is dev,
    # and a holdout id under it used to select nothing without a word: code review)
    split = "all" if args.cases else args.split
    match args.action:
        case "export":
            tracks = env_tracks(env)
            contexts = {t.slug: line_context(t) for t in tracks}
            roots = [root, *(Path(r) for r in args.roots)]
            cases = pb.export(roots, contexts, bench)
            held = sum(1 for c in cases if c.split == "holdout")
            lines = [f"{len(cases)} cases ({held} holdout) → {bench / 'cases'}"]
        case "bench":
            instructions = (
                Path(args.prompt).read_text(encoding="utf-8") if args.prompt else INSTRUCTIONS
            )
            try:
                spec = parse_model(args.model) if args.model else prose_model_spec(env)
                auth = prose_auth(env, spec)
            except (ModelSpecError, MissingCredentials) as e:
                sys.stderr.write(f"{e}\n")
                return 1
            variant = pb.Variant(
                name=str(args.variant),
                instructions=instructions,
                model=str(spec),
                thinking=not args.no_thinking,
                sources=bool(args.sources),
                check=Path(args.check).read_text(encoding="utf-8") if args.check else None,
                lang=note_lang({NOTE_LANG_ENV: str(args.lang)}),
            )
            async with httpx2.AsyncClient(timeout=pb.PROSE_TIMEOUT_S) as http:
                lines = await pb.run_bench(
                    bench,
                    variant,
                    writer=Writer(auth, http),
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
        case "judge" | "comprehend" | "scores":
            evaluated = await _prose_eval(env, args, bench)
            if evaluated is None:
                return 1
            lines = evaluated
        case _:
            if args.verdicts:
                lines = pb.gate_summary(bench, str(args.variant), Path(args.verdicts))
            else:
                rubric = RUBRICS[pb.variant_lang(bench, str(args.variant))].read_text(
                    encoding="utf-8"
                )
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
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
            lines = await check_queries(env, slug, http=http, now=datetime.now().astimezone())
    except NoQuestions as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


async def _codex_login(env: Mapping[str, str]) -> int:
    """A browser login of the pipeline's own (generation.codex): run once in a terminal on
    the machine that runs launchd, and again if a run reports the grant was rejected."""
    path = codex_auth_path(env)

    def show(url: str) -> None:
        sys.stdout.write(f"Sign in to ChatGPT in the browser (if none opens, visit):\n{url}\n")
        sys.stdout.flush()
        webbrowser.open(url)

    await login(path, show=show)
    sys.stdout.write(f"Codex login saved → {path}\n")
    return 0


def _prepared(env: Mapping[str, str]) -> None:
    for note in prepare_store(store_dir(env)):
        sys.stdout.write(f"{note}\n")
