"""`jrp init` and `jrp try`: the first hour without the author's machine (plan
productize-en-zh P2).

`jrp init` writes what a run reads, where jrp looks for it by default (home.py): the env
file, config.toml with one line, and that line's question file with one open question and
its query lines. A file that exists is never touched — init is safe to run again, and
it never edits a setup someone already has.

`jrp try --line <slug>` runs that one line once into a scratch store and vault under
~/.local/share/jrp/try/<time>/, so a new question can be seen the same hour instead of
the next morning; the real store, vault and rotation are not touched.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Final

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.home import DATA_HOME, JRP_HOME
from jev_research_pipeline.note_text import Lang
from jev_research_pipeline.pipeline.config import env_tracks
from jev_research_pipeline.pipeline.runner import STORE_ENV, run_pipeline, run_summary
from jev_research_pipeline.report import VAULT_ENV

EXAMPLE_LINE: Final = "agent-memory"

ENV_TEMPLATE: Final = """\
# jrp: the environment of every run. A scheduled run sources this file; for a manual
# run: set -a; source ~/.config/jrp/env; set +a
# Reference: docs/configuration.md

# required
JRP_VAULT_DIR=""        # notes go to <this folder>/daily-research/ (an Obsidian vault or any folder)
TYPESAFE_API_KEY=""     # Jev, https://docs.typesafe.ai
JRP_STORE_DIR="{store}"   # the pipeline's state (one JSON-LD file per line)

JRP_NOTE_LANG={lang}         # the note's language: ja | en | zh

# The writer of the prose, <backend>:<model>:
#   openai-codex:gpt-6-luna        (default) your ChatGPT subscription; sign in once: jrp codex login
#   claude-code:claude-opus-5-5    your Claude subscription through the Claude Code CLI (claude auth login)
#   dashscope:qwen3.7-max          pay as you go, needs DASHSCOPE_API_KEY
# JRP_PROSE_MODEL=openai-codex:gpt-6-luna

# optional
# JRP_COST_CAP_USD=0.50          # per line per run; past it the note is partial
# JRP_JEV_USD_PER_QUESTION=      # Jev unit price, for the note's cost line
# TAVILY_API_KEY=                # web search source (free tier: 1,000 searches a month)
# GITHUB_TOKEN=                  # raises the GitHub search limit
# OPENALEX_API_KEY=              # raises OpenAlex's daily budget
"""

CONFIG_TEMPLATE: Final = f"""\
# jrp lines: one [tracks.<slug>] table per research line ("track" and "line" mean the same).
# Reference: docs/configuration.md

[general]
lines_per_day = 3                  # lines picked per run, in a fixed rotation

[tracks.{EXAMPLE_LINE}]
name = "Agent memory"
# daily = true                     # run on every tick instead of taking turns
# [[tracks.{EXAMPLE_LINE}.repos]]
# target_repo = "~/projects/my-research"   # optional: its graph.jsonld adds vocabulary
"""

QUESTIONS_TEMPLATE: Final = f"""\
<!-- jrp:questions:{EXAMPLE_LINE} -->

## Which memory designs measurably change what an LLM agent gets right?
- slug: memory-designs
- version: 1
- status: open
- opened: {{today}}
- retire: close it when three months bring no new evidence
- brief: Long-term memory for LLM agents (retrieval, summaries, structured stores). Which design choices move downstream accuracy, and by how much, on public benchmarks.
- method: benchmark comparisons with the answering model held fixed
- evidence: measured results; a claim without a number is not enough
- not: prompt techniques in general
- arxiv: agent memory benchmark
- github: agent memory
- hf: long-term memory for LLM agents
"""


@dataclass(frozen=True)
class Written:
    path: Path
    created: bool
    """False = the file was already there and was left as it was."""


def _write_new(path: Path, text: str, *, private: bool = False) -> Written:
    if path.exists():
        return Written(path, created=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    # exclusive create: a file that appeared meanwhile is not overwritten either
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return Written(path, created=True)


def init(
    *,
    home: Path = JRP_HOME,
    store: Path = DATA_HOME / "store",
    lang: Lang = "en",
    today: str | None = None,
) -> list[Written]:
    """The env file (0600: it will hold keys), config.toml and the example line's question
    file, each only if missing."""
    day = today or datetime.now().astimezone().date().isoformat()
    return [
        _write_new(home / "env", ENV_TEMPLATE.format(lang=lang, store=store), private=True),
        _write_new(home / "config.toml", CONFIG_TEMPLATE),
        _write_new(home / "questions" / f"{EXAMPLE_LINE}.md", QUESTIONS_TEMPLATE.format(today=day)),
    ]


def init_lines(written: list[Written]) -> list[str]:
    lines = [f"{'created' if w.created else 'kept   '} {w.path}" for w in written]
    return [
        *lines,
        "",
        "Next:",
        "  1. Fill in JRP_VAULT_DIR and TYPESAFE_API_KEY in the env file.",
        "  2. Edit the question (or ask Claude Code with the jrp-question skill).",
        "  3. set -a; source ~/.config/jrp/env; set +a",
        "  4. jrp doctor                       # what a run needs, checked without a run",
        f"  5. jrp try --line {EXAMPLE_LINE}         # one run into a scratch folder, now",
    ]


def try_dirs(now: datetime, *, root: Path = DATA_HOME) -> tuple[Path, Path]:
    """A fresh scratch (store, vault) pair for one `jrp try`."""
    base = root / "try" / now.strftime("%Y%m%d-%H%M%S")
    store, vault = base / "store", base / "vault"
    store.mkdir(parents=True, exist_ok=True)
    vault.mkdir(parents=True, exist_ok=True)
    return store, vault


QUESTION_SKILL: Final = "jrp-question.md"
"""The skill `jrp questions new` hands to Claude Code: the package's copy of
.claude/skills/jrp-question/SKILL.md (tests/test_init.py pins the two equal), so an
installed jrp has it outside the repo."""


def question_session(binary: Path, slug: str, path: Path) -> list[str]:
    """The argv of an interactive Claude Code session that runs the jrp-question procedure
    for one line. Interactive, not `claude -p`: the procedure interviews the person."""
    skill = (files("jev_research_pipeline") / "skills" / QUESTION_SKILL).read_text(encoding="utf-8")
    exists = "It exists: read it first." if path.exists() else "It does not exist yet."
    ask = (
        f"Set up the questions of the jrp line `{slug}` with the procedure in your system "
        f"prompt. The question file is {path}. {exists}"
    )
    return [str(binary), "--append-system-prompt", skill, ask]


@dataclass(frozen=True)
class Tried:
    lines: list[str]
    """The run's summary, then one `note: <path>` per note written."""
    notes: list[Path]


async def try_line(
    env: Mapping[str, str],
    slug: str,
    *,
    http: httpx2.AsyncClient,
    now: AwareDatetime,
    root: Path = DATA_HOME,
) -> Tried | None:
    """Run `slug` once with the store and the vault pointed at try_dirs(); None when the
    config has no such line. Nothing is notified."""
    if slug not in {t.slug for t in env_tracks(env)}:
        return None
    store, vault = try_dirs(now, root=root)
    scratch = {**env, STORE_ENV: str(store), VAULT_ENV: str(vault)}
    unanswered: list[str] = []
    failed: list[str] = []
    outcomes = await run_pipeline(
        scratch, now=now, http=http, unanswered=unanswered, failed=failed, only=[slug]
    )
    title, body = run_summary(outcomes, skipped=unanswered, failed=failed)
    notes = [o.note for o in outcomes]
    return Tried(lines=[title, body, *(f"note: {n}" for n in notes)], notes=notes)
