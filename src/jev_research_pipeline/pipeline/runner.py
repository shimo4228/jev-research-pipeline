"""`jrp run`: harvest ticks first, then the next lines in rotation, one report each.

Environment (nothing is guessed):
    JRP_VAULT_DIR          vault root (required; nothing is written without it)
    JRP_STORE_DIR          pipeline store root (default ~/.local/share/jrp/store)
    TYPESAFE_API_KEY       Jev key (required)
    JRP_PROSE_MODEL        optional prose model, <backend>:<model>
                           (default openai-codex:gpt-6-luna; generation.client)
    JRP_CODEX_AUTH         optional path of the pipeline's Codex login
                           (default ~/.config/jrp/codex-auth.json; `jrp codex login`)
    DASHSCOPE_API_KEY      required only for a dashscope: prose model
    TAVILY_API_KEY         optional; web_search is skipped without it
    GITHUB_TOKEN           optional; raises the GitHub search limit
    JRP_COST_CAP_USD       optional cost cap per line-run → partial report
    JRP_JEV_USD_PER_QUESTION  optional Jev price for the cost meter
    JRP_DAILY_RESEARCH_CONFIG  optional config.toml path (default ~/.config/jrp/config.toml)
    JRP_QUESTIONS_DIR      optional question-file root (default ~/.config/jrp/questions)
    JRP_GITHUB_OWNER       optional; line @ids from github.com/<owner> (pipeline.config)
    JRP_JEV_CONCURRENCY    optional Jev requests in flight (default 12; pipeline.concurrency)
    JRP_PROSE_CONCURRENCY  optional prose calls in flight (default 3)
    JRP_NOTE_LANG          optional note language, ja | en | zh (default ja; note_text)

The store is checked before anything else (store.migrate.prepare_store).
"""

import asyncio
import tomllib
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Final

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline import note_text as t
from jev_research_pipeline.generation import (
    MissingCredentials,
    ModelSpecError,
    ProseAuth,
    Writer,
    prose_auth,
)
from jev_research_pipeline.home import DATA_HOME
from jev_research_pipeline.jev.core import JEV_REQUESTS_PER_MINUTE, RequestPacer
from jev_research_pipeline.model import GraphNodeType, Label, QuestionLog, Report
from jev_research_pipeline.note_text import DEFAULT_LANG, BadNoteLang, Lang, note_lang
from jev_research_pipeline.questions import (
    NO_QUESTIONS,
    NoQuestions,
    open_questions,
    question_queries,
)
from jev_research_pipeline.reduction.used import (
    Scan,
    mark_used,
    record_sightings,
    scan_documents,
    unread_paths,
)
from jev_research_pipeline.report import harvest_note, note_report_id, report_notes, vault_dir
from jev_research_pipeline.store import GraphStore, advance_rotation
from jev_research_pipeline.store.migrate import StoreSchemaError, prepare_store

from .config import TrackSpec, config_path, env_tracks, line_context, rotation_config
from .nets import DayBudget, for_line, load_nets
from .run import Keys, LineOutcome, LineRun

STORE_ENV: Final = "JRP_STORE_DIR"
DEFAULT_STORE: Final = DATA_HOME / "store"
KEY_ENVS: Final = ("TYPESAFE_API_KEY",)


class MissingKey(RuntimeError):
    pass


def store_dir(env: Mapping[str, str]) -> Path:
    raw = env.get(STORE_ENV)
    return Path(raw) if raw else DEFAULT_STORE


def keys(env: Mapping[str, str]) -> tuple[Keys, ProseAuth]:
    """Everything a run needs to reach Jev and the prose model, checked before the store is
    touched: a missing key or login stops the run at the start, not halfway through."""
    missing = [k for k in KEY_ENVS if not env.get(k)]
    if missing:
        raise MissingKey(f"missing env: {', '.join(missing)}")
    try:
        prose = prose_auth(env)
        note_lang(env)
    except (ModelSpecError, MissingCredentials, BadNoteLang) as e:
        raise MissingKey(str(e)) from e
    return Keys(typesafe=env["TYPESAFE_API_KEY"]), prose


def harvest_line(
    store: GraphStore,
    vault: Path,
    slug: str,
    now: AwareDatetime,
    lang: Lang = DEFAULT_LANG,
) -> list[str]:
    """Labels from every jrp note of the line into its partition. Nothing is written to the
    question file: questions are the author's (design "Authored queries"). Each Label keeps
    the `first_harvested_at` of the Label already stored under its @id (see
    `_first_harvest`)."""
    part = store.line(slug)
    nodes = part.load()
    reports = {n.id: n for n in nodes.values() if isinstance(n, Report)}
    logs = {
        f"{n.question}:{n.run_date.isoformat()}": n
        for n in nodes.values()
        if isinstance(n, QuestionLog)
    }
    labels = withdrawn = 0
    skipped: list[str] = []
    for note in report_notes(vault, slug):
        report = reports.get(note_report_id(note) or "")
        if report is None:
            skipped.append(f"{note.name}: unknown_report")
            continue
        result = harvest_note(note, now=now, report_claims=frozenset(report.claims), logs=logs)
        if result.skipped is not None:
            skipped.append(f"{note.name}: {result.skipped}")
            continue
        part.put(_first_harvest(result.labels, nodes, now))
        # `cleared` lists every blank box of the note (a blank question-day expands to the
        # day and all it cites), re-listed on every run; only the Labels actually dropped
        # are a withdrawal worth reporting.
        withdrawn += part.remove(result.cleared)
        labels += len(result.labels)
    lines = [t.HARVEST(lang, labels=labels, withdrawn=withdrawn)]
    return lines + [f"harvest skip: {s}" for s in skipped]


def _first_harvest(
    labels: Sequence[Label], stored: Mapping[str, GraphNodeType], now: AwareDatetime
) -> list[Label]:
    """A Label already stored under the same @id passes its `first_harvested_at` on, None
    included: a tick harvested before the field existed stays unknown instead of turning
    into a new tick on the morning this build is deployed. Only a Label with no stored
    predecessor gets `now`. `stored` is the partition as loaded before this harvest, so a
    Label withdrawn by an earlier harvest (blank box) starts over when ticked again."""
    out: list[Label] = []
    for label in labels:
        prior = stored.get(label.id)
        first = prior.first_harvested_at if isinstance(prior, Label) else now
        out.append(label.model_copy(update={"first_harvested_at": first}))
    return out


def update_used(
    store: GraphStore,
    tracks: Sequence[TrackSpec],
    vault: Path,
    slugs: Sequence[str],
    now: AwareDatetime,
) -> tuple[list[str], Scan | None]:
    """Used rate, a measurement beside the ticks (reduction.used): scan the author's
    documents once for keys seen for the first time, then settle each line's UsedMarks.
    It reads graph.jsonld, docs/adr/ and the vault and writes only the store. Success is
    silent (the note's used-rate line is its output); a failure is one line in the note,
    never the end of the run, because nothing depends on this measurement."""
    try:
        repos = [t.repo for t in tracks if t.repo is not None]
        owner = next((t.owner for t in tracks if t.owner), None)
        pipeline = store.pipeline()
        scan = scan_documents(repos, vault, owner=owner, prior_unread=unread_paths(pipeline))
        today = now.date()
        sightings = record_sightings(pipeline, scan, today)
        for slug in slugs:
            mark_used(store.line(slug), sightings, today)
    except (OSError, ValueError) as e:
        return [f"used skip: {type(e).__name__}: {' '.join(str(e).split())[:160]}"], None
    return [], scan


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
    failed: list[str] | None = None,
    only: Sequence[str] | None = None,
) -> list[LineOutcome]:
    """`unanswered` collects the lines skipped for having no open question, so the caller
    can show them (the CLI prints them; a silent skip would look like a quiet success).
    `failed` collects the lines that raised; without it they go to `unanswered`.
    `only` runs exactly these lines and leaves the rotation where it is (`jrp try`)."""
    unanswered = unanswered if unanswered is not None else []
    failed = failed if failed is not None else unanswered
    vault = vault_dir(env)
    api_keys, prose = keys(env)
    # One writer for the whole tick: the lines share its provider (and so the Codex login).
    writer = Writer(prose, http)
    cfg = config_path(env)
    tracks = {t.slug: t for t in env_tracks(env)}
    rotation = rotation_config(list(tracks.values()), per_tick=lines_per_day(cfg))
    net_config = load_nets(cfg)
    day_budget = DayBudget()  # the daily quotas are shared by every line of the rotation
    store = GraphStore(store_dir(env))
    # Before anything is read: an old store is migrated (additive) or stops the run here
    # with one line (incompatible), never halfway through a line.
    lang = note_lang(env)
    migrated = prepare_store(store.root, lang)
    # A daily track runs on every tick, beside the rotation (daily-research's `daily = true`).
    daily = tuple(t.slug for t in tracks.values() if t.daily)
    harvested = {
        slug: [
            *(n for n in migrated if f"lines/{slug}.jsonld" in n),
            *harvest_line(store, vault, slug, now, lang),
        ]
        for slug in (only or (*rotation.order, *daily))
    }
    used_note, used_scan = update_used(store, list(tracks.values()), vault, tuple(harvested), now)
    for slug in harvested:
        harvested[slug].extend(used_note)
    picked = tuple(only) if only else (*advance_rotation(store, rotation, now), *daily)
    # One Jev rate window for the whole tick: the limit is per key, not per line.
    pacer = RequestPacer(JEV_REQUESTS_PER_MINUTE)

    async def one(slug: str) -> LineOutcome | None:
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
            return None
        run = LineRun(
            ctx=ctx,
            questions=questions,
            partition=store.line(slug),
            index_path=store.root / "index" / f"{slug}.sqlite",
            vault=vault,
            http=http,
            keys=api_keys,
            writer=writer,
            env=env,
            now=now,
            harvest_notes=harvested[slug],
            used_scan=used_scan,
            net_config=for_line(cfg, slug, net_config),
            day_budget=day_budget,
            pacing=pacing,
            queries=question_queries(env, slug, questions),
        )
        run.jev.pacer = pacer
        return await run.execute()

    # The lines run side by side: each has its own partition, meters and note; what they
    # share (the Jev rate window, adapter pacing per source, the day's OpenAlex credits)
    # is shared explicitly.
    async def guarded(slug: str) -> LineOutcome | None:
        # One line's failure is one line in the CLI output, not the end of the others
        # (they share the HTTP client, and would be cancelled mid-spend).
        try:
            return await one(slug)
        except (StoreSchemaError, MissingKey):
            raise
        except Exception as e:
            detail = " ".join(str(e).split())[:160]
            failed.append(f"{slug}: 失敗 ({type(e).__name__}: {detail})")
            return None

    ran = await asyncio.gather(*(guarded(slug) for slug in picked))
    return [o for o in ran if o is not None]


def run_summary(
    outcomes: Sequence[LineOutcome], *, skipped: Sequence[str], failed: Sequence[str]
) -> tuple[str, str]:
    """(title, body) of the one message a finished run sends. The title says DEGRADED when
    a line raised or any line's health has a reason (pipeline.health), and each such line
    gets one `DEGRADED <note>: <reasons>` line under the claims summary — a template day
    must not read like a quiet one. Lines skipped for want of a question follow, as before."""
    summary = ", ".join(
        f"{o.report.run_date} {o.note.stem}: {len(o.report.claims)} claims" for o in outcomes
    )
    degraded = [
        f"DEGRADED {o.note.stem}: {'; '.join(reasons)}"
        for o in outcomes
        if (reasons := o.health.reasons())
    ]
    title = "jrp run DEGRADED" if degraded or failed else "jrp run"
    return title, "\n".join([summary or "no line ran", *degraded, *failed, *skipped])
