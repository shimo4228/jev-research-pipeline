"""The author's question file: `questions/<slug>.md`, read every run, never written by a run.

The Question is the unit of the pipeline, and which questions are open is the author's
call (packet "Question-centric redesign"; since "Authored queries", nothing is proposed).
So this file is plain Markdown the author edits by hand (or Claude in the author's
session, AGENTS.md); no run writes to it.

Format — one `## ` block per question, fields as `- key: value` lines and list sections:

    <!-- jrp:questions:<line slug> -->

    ## エージェントの記憶は何で決まるのか
    - slug: agent-memory
    - version: 1
    - status: open
    - opened: 2026-09-23
    - retire: 三ヶ月 evidence が増えなければ閉じる
    - brief: 記憶機構の違いが下流の精度をどれだけ動かすか。
    - method: RAG / 長文 context
    - evidence: 測定されたもの。主張だけのものは採らない
    - not: プロンプト技法一般
    - canary: https://arxiv.org/abs/2609.01234

`slug` and `version` identify the Question node; everything else is wording the author
owns. A missing `slug` is derived from the heading, a missing `version` is 1. A file with
no open question stops the line's run ("問い未設定") rather than running a question-less
pipeline that would have nothing to anchor its judgments on.

Search queries are written into the same block, one line per query, keyed by adapter:

    - arxiv: agent memory benchmark
    - github: agent memory
    - hf: long-term memory for LLM agents
    - web: agent memory evaluation

They are authored when the question is (by the author, or by Claude in the author's
session — never at run time), trial-fetched with `jrp queries check`, and rewritten when
the question changes. A question runs on exactly its query lines; one without them sends
no keyword query (the note says so) while the other nets still run. arXiv ANDs every word
(`all:w1 AND all:w2`), so its queries stay two to four words.
"""

import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Final

from pydantic import AwareDatetime

from jev_research_pipeline.model import AdapterKind, GraphNodeType, Question, QuestionStatus

type AuthoredQueries = tuple[tuple[AdapterKind, str], ...]
"""One question's query lines, (adapter, text), in file order."""

QUERY_FIELDS: Final[Mapping[str, AdapterKind]] = {
    "arxiv": "arxiv",
    "github": "github",
    "hf": "hf_papers",
    "web": "web_search",
}
"""Field key in the question block → the keyword adapter it is sent to."""

QUESTIONS_ENV: Final = "JRP_QUESTIONS_DIR"
DEFAULT_QUESTIONS_DIR: Final = Path("questions")
NO_QUESTIONS: Final = "問い未設定"
"""Why a line's run stops: the author has not opened a question for it yet."""

_HEADING_RE: Final = re.compile(r"^##\s+(.+?)\s*$")
_FIELD_RE: Final = re.compile(r"^-\s*([a-z]+)\s*:\s*(.*?)\s*$")
_SLUG_STRIP_RE: Final = re.compile(r"[^0-9a-z]+")
_MULTI: Final = {
    "method": "method_constraints",
    "evidence": "evidence_constraints",
    "not": "negative_topics",
}


class NoQuestions(RuntimeError):
    """A line with no open question. The run stops here by design."""

    def __init__(self, slug: str, path: Path) -> None:
        super().__init__(f"{NO_QUESTIONS}: {slug} ({path})")
        self.slug = slug
        self.path = path


def questions_dir(env: Mapping[str, str]) -> Path:
    raw = env.get(QUESTIONS_ENV)
    return Path(raw) if raw else DEFAULT_QUESTIONS_DIR


def questions_path(env: Mapping[str, str], slug: str) -> Path:
    return questions_dir(env) / f"{slug}.md"


def slugify(title: str) -> str:
    """A kebab slug from a title. Non-ASCII titles (the usual case) keep no letters, so
    they fall back to a short hash of the title — stable, and never empty."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    slug = _SLUG_STRIP_RE.sub("-", folded).strip("-")
    if not slug:
        from jev_research_pipeline.model import sha256_hex

        return f"q-{sha256_hex(title)[:8]}"
    return slug[:40].strip("-")


def _blocks(text: str) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            current = []
            blocks.append((heading.group(1), current))
        elif current is not None:
            current.append(line)
    return blocks


def _fields(lines: Sequence[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in lines:
        m = _FIELD_RE.match(line)
        if m and m.group(2):
            key = _MULTI.get(m.group(1), m.group(1))
            out.setdefault(key, []).append(m.group(2))
    return out


def _status(raw: str) -> QuestionStatus:
    return raw if raw in ("open", "answered", "dropped") else "open"


def parse_questions(text: str, *, line: str, opened_at: AwareDatetime) -> list[Question]:
    """Every question in the file, in file order. A block that cannot be a Question
    (no title, or an unusable field) is skipped rather than failing the run."""
    questions: list[Question] = []
    for title, lines in _blocks(text):
        fields = _fields(lines)
        one = {k: v[0] for k, v in fields.items()}
        opened = one.get("opened")
        try:
            questions.append(
                Question.new(
                    line=line,
                    slug=one.get("slug") or slugify(title),
                    version=int(one.get("version", "1")),
                    title=title,
                    brief=one.get("brief", ""),
                    status=_status(one.get("status", "open")),
                    retire_rule=one.get("retire", ""),
                    method_constraints=tuple(fields.get("method_constraints", ())),
                    evidence_constraints=tuple(fields.get("evidence_constraints", ())),
                    negative_topics=tuple(fields.get("negative_topics", ())),
                    canary_papers=tuple(fields.get("canary", ())),
                    opened_at=_opened(opened, opened_at),
                )
            )
        except (ValueError, TypeError):
            continue
    return questions


def _opened(raw: str | None, fallback: AwareDatetime) -> AwareDatetime:
    if raw:
        try:
            return fallback.replace(
                year=date.fromisoformat(raw).year,
                month=date.fromisoformat(raw).month,
                day=date.fromisoformat(raw).day,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        except ValueError:
            pass
    return fallback


def open_questions(
    env: Mapping[str, str],
    slug: str,
    *,
    line: str,
    now: AwareDatetime,
    stored: Mapping[str, GraphNodeType] | None = None,
    evidence_scope: Collection[str] | None = None,
) -> list[Question]:
    """The line's open questions. Raises NoQuestions when there are none: a run without a
    question has nothing to anchor a judgment on, and would spend the budget saying so.

    The file carries the author's wording; the store carries the evidence set that grew
    under it. `stored` merges the latter back in — without it every run would screen, judge
    novelty and measure movement against an empty evidence set. `evidence_scope` limits it
    to the claims accepted on earlier days, so today's own accepts do not change the state
    mid-run: a same-day re-run then asks Jev exactly the questions the first run asked.
    """
    path = questions_path(env, slug)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    questions = [q for q in parse_questions(text, line=line, opened_at=now) if q.status == "open"]
    if not questions:
        raise NoQuestions(slug, path)
    known = stored or {}

    def merged(question: Question) -> Question:
        node = known.get(question.id)
        if not isinstance(node, Question):
            return question
        evidence = tuple(i for i in node.evidence if evidence_scope is None or i in evidence_scope)
        return question.model_copy(update={"evidence": evidence}) if evidence else question

    return [merged(q) for q in questions]


def parse_queries(text: str) -> dict[str, AuthoredQueries]:
    """Each block's query lines, keyed by the block's slug (derived the way parse_questions
    derives it). A block without query lines is absent."""
    out: dict[str, AuthoredQueries] = {}
    for title, lines in _blocks(text):
        fields = _fields(lines)
        slug = fields.get("slug", [""])[0] or slugify(title)
        queries: list[tuple[AdapterKind, str]] = []
        for line in lines:  # file order across adapters, which _fields does not keep
            m = _FIELD_RE.match(line)
            if m and m.group(2) and (kind := QUERY_FIELDS.get(m.group(1))) is not None:
                queries.append((kind, m.group(2)))
        if queries:
            out[slug] = tuple(queries)
    return out


def question_queries(
    env: Mapping[str, str], slug: str, questions: Sequence[Question]
) -> dict[str, AuthoredQueries]:
    """The authored queries of `questions`, keyed by Question @id."""
    path = questions_path(env, slug)
    by_slug = parse_queries(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {q.id: by_slug[q.slug] for q in questions if q.slug in by_slug}
