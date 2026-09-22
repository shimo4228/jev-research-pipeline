"""The author's question file: `questions/<slug>.md`, read every run, written only on a tick.

The Question is the unit of the pipeline, and which questions are open is the author's
call — the pipeline proposes, the author disposes (packet "Question-centric redesign").
So this file is plain Markdown the author edits by hand, and the pipeline only ever
appends a question the author ticked in a note.

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
"""

import re
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Final

from pydantic import AwareDatetime

from jev_research_pipeline.model import Question, QuestionStatus

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
_LIST_FIELDS: Final = ("method_constraints", "evidence_constraints", "negative_topics", "canary")


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
    env: Mapping[str, str], slug: str, *, line: str, now: AwareDatetime
) -> list[Question]:
    """The line's open questions. Raises NoQuestions when there are none: a run without a
    question has nothing to anchor a judgment on, and would spend the budget saying so."""
    path = questions_path(env, slug)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    questions = [q for q in parse_questions(text, line=line, opened_at=now) if q.status == "open"]
    if not questions:
        raise NoQuestions(slug, path)
    return questions


def render_question(question: Question) -> str:
    """One `## ` block, in the shape parse_questions() reads back."""
    lines = [
        f"## {question.title}",
        f"- slug: {question.slug}",
        f"- version: {question.version}",
        f"- status: {question.status}",
        f"- opened: {question.opened_at.date().isoformat()}",
    ]
    if question.retire_rule:
        lines.append(f"- retire: {question.retire_rule}")
    if question.brief:
        lines.append(f"- brief: {question.brief}")
    for field, key in zip(_LIST_FIELDS, ("method", "evidence", "not", "canary"), strict=True):
        values = getattr(question, "canary_papers" if field == "canary" else field)
        lines += [f"- {key}: {value}" for value in values]
    return "\n".join(lines) + "\n"


def append_question(env: Mapping[str, str], slug: str, question: Question) -> Path:
    """Append one adopted question to the line's file (created if missing). A question
    whose slug is already in the file is left alone: the author's wording wins."""
    path = questions_path(env, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        path.read_text(encoding="utf-8") if path.is_file() else f"<!-- jrp:questions:{slug} -->\n"
    )
    if any(f"- slug: {question.slug}" == line.strip() for line in text.splitlines()):
        return path
    body = text.rstrip("\n") + "\n\n" + render_question(question)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(body)
        handle.flush()
        temp = Path(handle.name)
    temp.replace(path)
    return path
