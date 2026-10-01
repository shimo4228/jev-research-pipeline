"""Report markdown (packet "Question-centric redesign").

    ---                                  frontmatter: daily-research keys (date / category /
    date / category: jrp / kind / tags /   kind / tags / topic) + line + jrp_report
    topic / line / jrp_report
    ---
    # <line name> — <date>
    ### <question title>                 one section per question that moved today
    今日の変化
    <prose, with [n] and one inference paragraph marked 推論>
    証拠
    - <source title> — <gist> — [link](url)
    反証                                 claims that count against the answer, if any
    - [ ] 読む価値があった <!-- jrp:qday:<question @id>:<date> -->
    ## Review                            borderline sources, one checkbox each
    - [ ] <title> — <why> <!-- jrp:source:<source @id> -->
    ## 橋渡し                              what the exploration nets connected
    > [!note]- Claims                    folded: the wall of claims is not the reading surface
    > - [ ] <verbatim> — [source](url) <!-- jrp:claim:<claim @id> -->
    ## 未判定
    - [<Jev function>] <source title | claim text | question title>
    ## 運用

The fixed text above is the Japanese of note_text (JRP_NOTE_LANG picks en or zh); the
marks, `## Review` and the folded Claims are the same in every language.

The machine-read lines are exactly the three `<!-- jrp:… -->` marks above; one checkbox
per question-day is the primary metric's unit, and its tick propagates to the claims and
sources cited under it (report.vault).

Everything that came from outside (claim text, generated prose, unjudged snippets,
operations notes) passes through sanitize(). The boundary is *executable or fetching*
syntax, not markdown: outside text may render as an ordinary link, a bare URL, a #tag or
an inline code span, but never as a wikilink / embed / remote image / HTML / code fence
(``` or ~~~) / Dataview or Templater expression / javascript: or data: link — and it
must never be able to forge a `<!-- jrp:… -->` line. Source URLs pass through
safe_url() (http(s) only, markdown-breaking characters percent-encoded).
"""

import json
import re
from collections.abc import Callable
from datetime import date
from typing import Final
from urllib.parse import quote

from jev_research_pipeline import note_text as t
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import Claim, JevFunction, Report
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.note_text import Lang

CATEGORY: Final = "jrp"
KIND: Final = "report"
CLAIM_MARK: Final = "jrp:claim:"
QDAY_MARK: Final = "jrp:qday:"
SOURCE_MARK: Final = "jrp:source:"

# Only syntax Obsidian (or a plugin) would *execute or fetch* is neutralized — the live
# notes showed that escaping every bracket, paren, $ and < made them unreadable in source
# view. Plain prose, inline code spans and ordinary links stay as written.
type _Repl = str | Callable[[re.Match[str]], str]


def _escape_each(m: re.Match[str]) -> str:
    """Backslash every character of the matched run (a half-escaped fence still fences)."""
    return "".join("\\" + c for c in m.group(0))


_ESCAPES: Final[tuple[tuple[re.Pattern[str], _Repl], ...]] = (
    # Wikilinks and embeds: [[note]], ![[file]], and ![alt](url) (a remote embed fetches).
    # Every bracket of a run of 2+, so an odd run ([[[x]]]) cannot leave a live [[.
    (re.compile(r"\[{2,}"), _escape_each),
    (re.compile(r"!\["), "!\\["),
    # Obsidian comments: every % inside a run of 2+ (an odd run must not re-form %%).
    (re.compile(r"%(?=%)|(?<=%)%"), "\\%"),
    # Code fences anywhere (``` and ~~~): dataview / dataviewjs blocks run on render, and
    # CommonMark accepts them indented up to 3 spaces or inside a list item or quote — so
    # position is not a safe filter. Inline code spans use 1-2 backticks and survive.
    (re.compile(r"[`~]{3,}"), _escape_each),
    # Inline Dataview queries: `= expr` and `$= js`.
    (re.compile(r"`(\s*\$?)="), r"\\`\1\\="),
    # HTML / Templater: only a < that opens a tag, comment or <% … %>.
    (re.compile(r"<(?=[/!?%a-zA-Z])"), "&lt;"),
    # Headings and task lines forged at line start.
    (re.compile(r"(?m)^(\s*)#"), r"\1\\#"),
    (re.compile(r"(?m)^(\s*[-*+] )\["), r"\1\\["),
    # Script-ish link targets: break the link syntax itself. Entity-encoding the colon is
    # not enough — CommonMark decodes entities inside a link destination.
    (re.compile(r"(?i)\]\(\s*(javascript|data):"), r"]\\(\1:"),
)


class ClaimEntry(Value):
    claim: Claim
    source_url: str
    cite: str = ""
    """Which [n] of which question section cites it ("<question> [n]"): the prose numbers
    claims per section, so a folded list of the whole day needs the key to be followed."""


class SourceEntry(Value):
    """One source line under 証拠, Review or 橋渡し."""

    source_id: str
    title: str
    gist: str
    url: str


class UnjudgedEntry(Value):
    """One subject whose Jev request failed, with the function that failed. The 未判定 list
    mixes source titles (screening), claim texts (novelty, support) and question titles
    (movement); without the function a failed movement check reads like a claim."""

    function: JevFunction
    text: str


class QuestionSection(Value):
    """One question that moved today. `prose` is None when the ladder fell to template."""

    question_id: str
    title: str
    prose: str | None
    evidence: tuple[SourceEntry, ...]
    contradictions: tuple[str, ...] = ()
    """Claims that count against the answer the evidence set supports. They get their own
    block rather than being folded into the day's prose: a contradiction the reader has to
    dig for is a contradiction that does not do its work."""


def sanitize(text: str, *, one_line: bool = False) -> str:
    """Untrusted text → text that renders but never executes or fetches."""
    out = text
    for pattern, repl in _ESCAPES:
        out = pattern.sub(repl, out)
    return " ".join(out.split()) if one_line else out


def safe_url(url: str) -> str | None:
    """http(s) URL with markdown-breaking characters percent-encoded; None for anything else."""
    if not url.startswith(("https://", "http://")):
        return None
    # A % not starting a valid escape is encoded, so no %% (an Obsidian comment) can appear.
    url = re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", url)
    return quote(url, safe=":/?#@!&=+,;%~-._*'")


def _frontmatter(report: Report, ctx: LineContext, n_sections: int, lang: Lang) -> str:
    topic = t.TOPIC(lang, line=ctx.line.name, n=n_sections)
    fields = [
        f"date: {report.run_date.isoformat()}",
        f"category: {CATEGORY}",
        f"kind: {KIND}",
        f"tags: [{CATEGORY}, {ctx.line.slug}]",
        f"topic: {json.dumps(topic, ensure_ascii=False)}",
        f"line: {ctx.line.slug}",
        f"jrp_report: {json.dumps(report.id)}",
    ]
    return "---\n" + "\n".join(fields) + "\n---\n"


def claim_line(entry: ClaimEntry) -> str:
    url = safe_url(entry.source_url)
    link = f" — [source]({url})" if url else ""
    cite = f"**{sanitize(entry.cite, one_line=True)}** " if entry.cite else ""
    text = sanitize(entry.claim.text, one_line=True)
    return f"- [ ] {cite}{text}{link} <!-- {CLAIM_MARK}{entry.claim.id} -->"


def _source_line(entry: SourceEntry, mark: str | None = None) -> str:
    url = safe_url(entry.url)
    link = f" — [link]({url})" if url else ""
    gist = f" — {sanitize(entry.gist, one_line=True)}" if entry.gist else ""
    box = "- [ ] " if mark else "- "
    tail = f" <!-- {mark} -->" if mark else ""
    return f"{box}{sanitize(entry.title, one_line=True)}{gist}{link}{tail}"


def qday_mark(question_id: str, run_date: date) -> str:
    return f"{QDAY_MARK}{question_id}:{run_date.isoformat()}"


def _question_section(section: QuestionSection, run_date: date, lang: Lang) -> str:
    body = sanitize(section.prose) if section.prose is not None else t.TEMPLATE_BODY(lang)
    lines = [
        f"### {sanitize(section.title, one_line=True)}",
        "",
        t.CHANGES(lang),
        "",
        body,
        "",
        t.EVIDENCE(lang),
        "",
        *[_source_line(e) for e in section.evidence],
        "",
        *(
            [
                t.COUNTER_EVIDENCE(lang),
                "",
                *[f"- {sanitize(c, one_line=True)}" for c in section.contradictions],
                "",
            ]
            if section.contradictions
            else []
        ),
        f"- [ ] {t.WORTH_READING(lang)} <!-- {qday_mark(section.question_id, run_date)} -->",
        "",
    ]
    return "\n".join(lines)


def _bullets(lines: list[str], lang: Lang) -> str:
    return ("\n".join(lines) + "\n") if lines else t.NONE_LISTED(lang) + "\n"


def render_report(
    *,
    report: Report,
    ctx: LineContext,
    sections: list[QuestionSection],
    claims: list[ClaimEntry],
    review: list[SourceEntry],
    bridges: list[SourceEntry],
    unjudged: list[UnjudgedEntry],
    operations: list[str],
    empty_day: str = "",
    lang: Lang = t.DEFAULT_LANG,
) -> str:
    """`sections` = the questions that moved today, in reading order; `claims` is the
    folded list (report.claims). Everything else is display lines, sanitized here.
    `empty_day` says why no question moved (what was fetched, how far it got) — a note
    that only says "nothing moved" cannot be told apart from a broken run. `lang` picks the
    fixed text (note_text); the marks and `## Review` / Claims are the same in every one."""
    date_ = report.run_date
    parts = [
        _frontmatter(report, ctx, len(sections), lang),
        f"# {sanitize(ctx.line.name, one_line=True)} — {date_.isoformat()}\n",
        "\n".join(_question_section(s, date_, lang) for s in sections)
        if sections
        else t.NOTHING_MOVED(lang, why=sanitize(empty_day, one_line=True)) + "\n",
        "## Review\n",
        _bullets([_source_line(e, f"{SOURCE_MARK}{e.source_id}") for e in review], lang),
        f"## {t.BRIDGES(lang)}\n",
        _bullets([_source_line(e) for e in bridges], lang),
        "> [!note]- Claims\n",
        _bullets([f"> {claim_line(e)}" for e in claims], lang),
        f"## {t.UNJUDGED(lang)}\n",
        _bullets([f"- [{u.function}] {sanitize(u.text, one_line=True)}" for u in unjudged], lang),
        f"## {t.OPERATIONS(lang)}\n",
        "\n".join(f"- {sanitize(o, one_line=True)}" for o in operations) + "\n",
    ]
    return "\n".join(parts)
