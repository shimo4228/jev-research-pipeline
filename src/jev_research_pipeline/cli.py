"""`jrp` — the pipeline's only entry point (launchd calls `jrp run`, and on Monday `jrp wbr`
after it; the weekly `jrp drift` job is stopped, launchd/README.md).

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
jrp drift          replay recorded Jev inputs live; needs JRP_DRIFT_LIVE=1; non-zero exit
                   when it compared nothing (pipeline.drift)
jrp migrate        bring the store up to today's schema; --dry-run prints the plan only
jrp wbr [--week YYYY-Www] [--out DIR]
                   the weekly review of one ISO week (default: the last complete one) from
                   the store alone: the note <DIR>/<the Monday after>_jrp_wbr.md (default
                   DIR <JRP_VAULT_DIR>/daily-research) and one line appended to
                   <store>/metrics/weekly.jsonl (pipeline.wbr); with ANTHROPIC_API_KEY set,
                   the monitoring judge's calls to the Claude API, one line each in
                   <store>/metrics/judge.jsonl (pipeline.monitor). An older store is read
                   under today's schema in memory, never migrated
jrp queries check --line <slug>
                   send each authored query once, print hits (pipeline.query_check)
jrp prose export|bench|read|gate
                   the prose bench: frozen inputs, variants, the author's blind reading file,
                   the fidelity judge's gate files (pipeline.prose_bench)
jrp codex login    sign in to the ChatGPT/Codex subscription once, for the default prose
                   model (generation.codex)
jrp eval gate [freeze|label|jitter|check] [--set NAME] [--candidate FILE]
                   the S (selection) and X (evidence, slots) eval on a frozen set under
                   <store>/evals/gate/NAME/: freeze it from the store, label its sample with
                   Claude Opus 5.5 (ANTHROPIC_API_KEY, JRP_EVAL_WEEKLY_USD), ask Jev the same
                   states again for the noise floor, write or read the author's blind check,
                   or (no action) score one candidate against today's run (evals.gate_score)

A store file from an older build stops every command with one line (store.migrate):
additive differences are migrated in place first (`jrp wbr`: lifted in memory, the file left
as it is), incompatible ones need `jrp migrate` (exit 2).
"""

import argparse
import asyncio
import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Final

import httpx2

from .evals.check import CHECK_N, read_check, render_agreement, write_check
from .evals.gate_run import freeze_lines, jitter_lines, label_lines, score_candidate
from .evals.gate_score import GateInputError, load_candidate
from .evals.gate_score import render as render_score
from .evals.gate_score import write as write_score
from .evals.gate_set import SINCE, GateSet, NoSet, freeze, load
from .evals.jitter import DEFAULT_MAX_QUESTIONS as JITTER_MAX_QUESTIONS
from .evals.jitter import DEFAULT_N as JITTER_N
from .evals.jitter import jitter
from .evals.paths import NAME as EVAL_NAME
from .evals.paths import eval_root
from .evals.silver import label, labels, ledger_path
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
from .pipeline.monitor import CALL_TIMEOUT_S
from .pipeline.notify import notify
from .pipeline.query_check import check_queries
from .pipeline.runner import run_pipeline, run_summary, store_dir
from .pipeline.wbr import Week, Written, write_weekly_review
from .questions import NoQuestions, questions_path
from .reduction import DecisionLog, export_cases, fit_thresholds, write_proposal
from .report import VaultNotConfigured, vault_dir
from .report.vault import REPORT_DIR
from .scheduling import install, install_lines
from .store import GraphStore
from .store.migrate import StoreSchemaError, migrate_store, prepare_store
from .telemetry import setup_telemetry

HTTP_TIMEOUT_S = 30.0
LOG_TIME_FORMAT: Final = "%Y-%m-%dT%H:%M:%S%z"
"""The time at the start of a timed log line, the same form scripts/launchd-jrp.sh's `say`
writes (tests pin the two equal), so one log reads one way."""


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
    w = sub.add_parser("wbr", help="the weekly review of one ISO week, from the store alone")
    w.add_argument(
        "--week", type=_iso_week, help="ISO week YYYY-Www (default: the last complete week)"
    )
    w.add_argument("--out", help="where the note goes (default: <JRP_VAULT_DIR>/daily-research)")
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
    _eval_parser(
        sub.add_parser("eval", help="offline evals of the pipeline's parts on frozen data")
    )
    return p


def _positive(text: str) -> int:
    """A count of 1 or more: 0 would read as 'use the default' and spend the default."""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more: {text}")
    return value


def _eval_parser(ev: argparse.ArgumentParser) -> None:
    """`jrp eval <part>`: the intake eval adds `intake` beside `gate` (evals/)."""
    evsub = ev.add_subparsers(dest="eval_command", required=True)
    g = evsub.add_parser("gate", help="S and X: score a candidate on the frozen set")
    g.add_argument(
        "action",
        nargs="?",
        default="score",
        choices=["score", "freeze", "label", "jitter", "check"],
    )
    g.add_argument("--set", dest="set_name", default="sx", help="the eval set's name")
    g.add_argument("--candidate", help="score: the candidate TOML (evals.gate_score)")
    g.add_argument("--since", type=date.fromisoformat, help="freeze: first day (YYYY-MM-DD)")
    g.add_argument("--limit", type=_positive, help="label: at most this many calls")
    g.add_argument("--n", type=_positive, help="jitter: states to ask again; check: items")
    g.add_argument(
        "--max-questions", type=_positive, help="jitter / ask candidate: Jev questions cap"
    )
    g.add_argument("--out", help="check: the page to write")
    g.add_argument("--read", help="check: the ticked page to read back")


def _iso_week(text: str) -> Week:
    try:
        return Week.parse(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _slugs(env: Mapping[str, str]) -> list[str]:
    return list(rotation_config(env_tracks(env), per_tick=1).order)


def _log_line(text: str) -> None:
    """One stdout line after the local time. Flushed at once: stdout into a log file is
    block-buffered, and a run killed by the watchdog would lose what the buffer held."""
    sys.stdout.write(f"{datetime.now().astimezone().strftime(LOG_TIME_FORMAT)} {text}\n")
    sys.stdout.flush()


async def _run(env: Mapping[str, str]) -> int:
    """The pipeline between a timed start line and a timed end line on stdout (the end line
    also when the run raises or is cancelled), so a log the launchd wrapper does not write
    (cron, systemd, a terminal) still says when the run ran and for how long. The message
    after them (run_summary) is the one Slack gets, unchanged."""
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
    _log_line("pipeline start")
    started = time.monotonic()
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
        _log_line(f"pipeline end · {round(time.monotonic() - started)} s")
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
    if found is None or {".venv", "archive-v0"} & set(Path(found).parts):
        # the job must name a jrp that stays: a checkout's .venv goes with the checkout, and
        # `uvx jrp` runs from an archive-v0 entry of uv's cache, which `uv cache clean` deletes
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


def _wbr(env: Mapping[str, str], week: Week | None, out: str | None) -> int:
    """Read-only on the store's partitions (pipeline.wbr): an incompatible partition raises
    StoreSchemaError, which main() prints as one line with exit 2. With ANTHROPIC_API_KEY
    set, the monitoring judge calls the Claude API (pipeline.monitor)."""
    now = datetime.now().astimezone()
    try:
        target = Path(out) if out else vault_dir(env) / REPORT_DIR
        written = asyncio.run(_weekly(env, week or Week.last_complete(now.date()), target, now))
    except StoreSchemaError:
        raise
    except (VaultNotConfigured, OSError, ValueError) as e:  # config, questions, JRP_NOTE_LANG
        sys.stderr.write(f"jrp wbr: {type(e).__name__}: {e}\n")
        return 1
    sys.stdout.write(f"{written.note}\n")
    return 0


async def _weekly(env: Mapping[str, str], week: Week, out: Path, now: datetime) -> Written:
    """One HTTP client for the monitoring judge; its per-call timeout is the judge's own."""
    async with httpx2.AsyncClient(timeout=CALL_TIMEOUT_S) as http:
        return await write_weekly_review(env, week=week, out=out, now=now, http=http)


def _fit(env: Mapping[str, str]) -> int:
    store = GraphStore(store_dir(env))
    for slug in _slugs(env):
        log = DecisionLog.from_partition(store.line(slug))
        skipped: list[str] = []
        proposals = fit_thresholds(log, skipped=skipped)
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
    """0 only when at least one answer was compared. Exit 2 = the live gate is closed (no
    message: a launchd job left loaded stays silent); exit 1 = it compared nothing (no
    cassette dir, no *.json in it, or no replay answered), sent as `jrp drift FAILED`."""
    if env.get(LIVE_ENV) != "1" or not env.get("TYPESAFE_API_KEY"):
        sys.stderr.write(f"drift calls the live API: set {LIVE_ENV}=1 and TYPESAFE_API_KEY\n")
        return 2
    paths = sorted(cassettes.glob("*.json")) if cassettes.is_dir() else []
    if not paths:
        state = "has no *.json cassette" if cassettes.is_dir() else "does not exist"
        return _drift_failed(env, f"nothing to compare: {cassettes} {state}")
    async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
        rows, failed = await drift_with_failures(paths, http, api_key=env["TYPESAFE_API_KEY"])
    if not rows:
        return _drift_failed(
            env, f"no answer compared: {len(paths)} cassettes, {failed} replays failed"
        )
    sys.stdout.write(drift_table(rows))
    worst = max(r.delta for r in rows)
    notify(
        "jrp drift",
        f"{len(rows)} answers compared, max Δp {worst:.3f}, {failed} replays failed",
        env=env,
    )
    return 0


def _drift_failed(env: Mapping[str, str], why: str) -> int:
    """Compared nothing: never the shape of "no drift" (0 answers is not Δp 0)."""
    sys.stderr.write(f"jrp drift: {why}\n")
    notify("jrp drift FAILED", why, env=env)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    env = dict(os.environ)
    setup_telemetry(env)  # no OTEL_EXPORTER_OTLP_ENDPOINT → no SDK, no-op spans
    try:
        match args.command:
            case "run":
                code = asyncio.run(_run(env))  # run_pipeline prepares the store itself
            case "fit" | "export-cases":
                _prepared(env)
                code = _fit(env) if args.command == "fit" else _export(env)
            case "migrate":
                code = _migrate(env, dry_run=bool(args.dry_run))
            case "doctor":
                code = _doctor(env)
            case "wbr":  # dispatched here, never into _async_command, whose fallback is drift
                code = _wbr(env, args.week, args.out)
            case _:
                code = asyncio.run(_async_command(env, args))
    except StoreSchemaError as e:
        sys.stderr.write(f"{e}\n")
        if args.command == "run":
            notify("jrp run STOPPED", str(e), env=env)
        return 2
    return code


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
        case "eval":
            code = await _eval_gate(env, args)
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
                rubric = pb.RUBRICS[pb.variant_lang(bench, str(args.variant))].read_text(
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


async def _eval_gate(env: Mapping[str, str], args: argparse.Namespace) -> int:
    """`jrp eval gate`: the S and X eval (evals.gate_set / gate_score / silver / jitter / check)."""
    name = str(args.set_name)
    if not EVAL_NAME.match(name) or ".." in name:
        sys.stderr.write(f"not an eval set name: {name!r}\n")
        return 1
    now = datetime.now().astimezone()
    try:
        if args.action == "freeze":
            frozen = freeze(env, name, since=args.since or SINCE)
            lines = freeze_lines(frozen)
        else:
            lines = await _eval_on_set(env, args, load(env, name), now)
    except (NoSet, GateInputError) as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


async def _eval_on_set(
    env: Mapping[str, str], args: argparse.Namespace, gs: GateSet, now: datetime
) -> list[str]:
    ledger = ledger_path(eval_root(env))
    lang = note_lang(env)
    match args.action:
        case "label":
            async with httpx2.AsyncClient(timeout=CALL_TIMEOUT_S) as http:
                got = await label(gs, env, ledger, http=http, now=now, lang=lang, limit=args.limit)
            return label_lines(got)
        case "jitter":
            async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
                result = await jitter(
                    gs,
                    env,
                    http=http,
                    now=now,
                    n=args.n or JITTER_N,
                    max_questions=args.max_questions or JITTER_MAX_QUESTIONS,
                )
            return jitter_lines(result)
        case "check":
            if args.read:
                return [render_agreement(read_check(Path(args.read)))]
            if not args.out:
                raise GateInputError("check: give --out PAGE to write, or --read PAGE to read back")
            n = write_check(
                gs, labels(ledger, gs.manifest.name, lang), Path(args.out), n=args.n or CHECK_N
            )
            if not n:
                raise GateInputError("check: no labelled item yet (run `jrp eval gate label`)")
            return [
                f"check page → {args.out}, {n} items (key: {Path(args.out).with_suffix('.key.json')})"
            ]
        case _:
            if not args.candidate:
                raise GateInputError("score: give --candidate FILE (bench/gate/candidates/*.toml)")
            candidate = load_candidate(Path(args.candidate))
            report = await score_candidate(
                gs, candidate, env, ledger, now=now, lang=lang, max_questions=args.max_questions
            )
            path = write_score(report, gs.root, now=now)
            return [render_score(report), f"→ {path}"]


def _prepared(env: Mapping[str, str]) -> None:
    for note in prepare_store(store_dir(env)):
        sys.stdout.write(f"{note}\n")
