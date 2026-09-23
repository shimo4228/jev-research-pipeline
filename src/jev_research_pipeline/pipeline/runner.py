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
    JRP_QUESTIONS_DIR      optional question-file root (default ./questions)
"""

import tomllib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Final

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.model import GraphNodeType, Question, QuestionLog, Report
from jev_research_pipeline.questions import NO_QUESTIONS, NoQuestions, open_questions
from jev_research_pipeline.report import harvest_note, note_report_id, report_notes, vault_dir
from jev_research_pipeline.store import GraphStore, advance_rotation
from jev_research_pipeline.store.migrate import prepare_store

from .config import config_path, line_context, line_seeds, load_tracks, rotation_config
from .nets import DayBudget, load_nets
from .run import Keys, LineOutcome, LineRun, adopt_candidates

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


def harvest_line(
    store: GraphStore, vault: Path, slug: str, now: AwareDatetime, env: Mapping[str, str]
) -> list[str]:
    """Labels from every jrp note of the line into its partition, and every adopted
    question proposal into the line's question file (the only write there)."""
    part = store.line(slug)
    nodes = part.load()
    reports = {n.id: n for n in nodes.values() if isinstance(n, Report)}
    logs = {
        f"{n.question}:{n.run_date.isoformat()}": n
        for n in nodes.values()
        if isinstance(n, QuestionLog)
    }
    proposals = {n.slug: n for n in nodes.values() if isinstance(n, Question)}
    labels = withdrawn = 0
    skipped: list[str] = []
    adopted: list[str] = []
    for note in report_notes(vault, slug):
        report = reports.get(note_report_id(note) or "")
        if report is None:
            skipped.append(f"{note.name}: unknown_report")
            continue
        result = harvest_note(note, now=now, report_claims=frozenset(report.claims), logs=logs)
        if result.skipped is not None:
            skipped.append(f"{note.name}: {result.skipped}")
            continue
        part.put(result.labels)
        part.remove(result.cleared)
        labels += len(result.labels)
        withdrawn += len(result.cleared)
        adopted += adopt_candidates(env, slug, result.adopted, proposals)
    lines = [f"harvest: label {labels} 件 / 取り消し {withdrawn} 件", *adopted]
    return lines + [f"harvest skip: {s}" for s in skipped]


def claims_before(nodes: Mapping[str, GraphNodeType], today: date) -> set[str]:
    """Claims reported on an earlier day. The evidence set is pinned to these so today's
    own accepts cannot change the state a re-run judges against."""
    return {
        claim
        for n in nodes.values()
        if isinstance(n, Report) and n.run_date < today
        for claim in n.claims
    }


def lines_per_day(config: Path) -> int:
    general = tomllib.loads(config.read_text(encoding="utf-8")).get("general", {})
    return int(general.get("lines_per_day", 3))


async def run_pipeline(
    env: Mapping[str, str],
    *,
    now: AwareDatetime,
    http: httpx2.AsyncClient,
    pacing: bool = True,
    unanswered: list[str] | None = None,
) -> list[LineOutcome]:
    """`unanswered` collects the lines skipped for having no open question, so the caller
    can show them (the CLI prints them; a silent skip would look like a quiet success)."""
    unanswered = unanswered if unanswered is not None else []
    vault = vault_dir(env)
    api_keys = keys(env)
    cfg = config_path(env)
    tracks = {t.slug: t for t in load_tracks(cfg)}
    rotation = rotation_config(list(tracks.values()), per_tick=lines_per_day(cfg))
    net_config = load_nets(cfg)
    day_budget = DayBudget()  # the daily quotas are shared by every line of the rotation
    store = GraphStore(store_dir(env))
    # Before anything is read: an old store is migrated (additive) or stops the run here
    # with one line (incompatible), never halfway through a line.
    migrated = prepare_store(store.root)
    harvested = {
        slug: [
            *(n for n in migrated if f"lines/{slug}.jsonld" in n),
            *harvest_line(store, vault, slug, now, env),
        ]
        for slug in rotation.order
    }
    outcomes: list[LineOutcome] = []
    for slug in advance_rotation(store, rotation, now):
        ctx = line_context(tracks[slug])
        try:
            nodes = store.line(slug).load()
            questions = open_questions(
                env,
                slug,
                line=ctx.line.id,
                now=now,
                stored=nodes,
                evidence_scope=claims_before(nodes, now.date()),
            )
        except NoQuestions as e:
            # By design: a line with no open question has nothing to anchor a judgment on.
            # The rotation has already advanced, so the next run moves on to the next line.
            unanswered.append(f"{slug}: {NO_QUESTIONS} ({e.path})")
            continue
        run = LineRun(
            ctx=ctx,
            questions=questions,
            seeds=line_seeds(tracks[slug]),
            partition=store.line(slug),
            index_path=store.root / "index" / f"{slug}.sqlite",
            vault=vault,
            http=http,
            keys=api_keys,
            env=env,
            now=now,
            harvest_notes=harvested[slug],
            net_config=net_config,
            day_budget=day_budget,
            pacing=pacing,
        )
        outcomes.append(await run.execute())
    return outcomes
