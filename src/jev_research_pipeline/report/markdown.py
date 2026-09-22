"""Report markdown (packet decision 12).

    ---                                  frontmatter: daily-research keys (date / category /
    date / category: jrp / kind / tags /   kind / tags / topic) + line + jrp_report
    topic / line / jrp_report
    ---
    # <line name> — <date>
    <prose, or the template notice>
    ## Claims                            one line per claim, the only machine-read lines:
    - [ ] <verbatim> — [source](url) <!-- jrp:claim:<claim @id> -->
    ## 未判定
    ## 運用

Everything that came from outside (claim text, generated prose, unjudged snippets,
operations notes) passes through sanitize(): Obsidian must render it as text, never as a
wikilink / embed / link (incl. bare-URL autolinks) / HTML / code fence (``` or ~~~) /
Dataview or Templater expression — and it
must never be able to forge a `<!-- jrp:claim -->` line. Source URLs pass through
safe_url() (http(s) only, markdown-breaking characters percent-encoded).
"""

import json
import re
from collections.abc import Callable
from typing import Final
from urllib.parse import quote

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import Claim, Report
from jev_research_pipeline.model.jsonld import Value

CATEGORY: Final = "jrp"
KIND: Final = "report"
CLAIM_MARK: Final = "jrp:claim:"

# Only syntax Obsidian (or a plugin) would *execute or fetch* is neutralized — the live
# notes showed that escaping every bracket, paren, $ and < made them unreadable in source
# view. Plain prose, inline code spans and ordinary links stay as written.
type _Repl = str | Callable[[re.Match[str]], str]


def _escape_each(m: re.Match[str]) -> str:
    """Backslash every character of the matched run (a half-escaped fence still fences)."""
    return "".join("\\" + c for c in m.group(0))


def _escape_brackets(m: re.Match[str]) -> str:
    return m.group(0).replace("[", "\\[")


_ESCAPES: Final[tuple[tuple[re.Pattern[str], _Repl], ...]] = (
    # Wikilinks and embeds: [[note]], ![[file]], and ![alt](url) (a remote embed fetches).
    (re.compile(r"!?\[\["), _escape_brackets),
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
    # Script-ish link targets: kept readable, no longer a usable href.
    (re.compile(r"(?i)\b(javascript|data):"), r"\1&#58;"),
)


class ClaimEntry(Value):
    claim: Claim
    source_url: str


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


def _frontmatter(report: Report, ctx: LineContext, n_claims: int) -> str:
    topic = f"{ctx.line.name} — {n_claims} claims"
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
    return f"- [ ] {sanitize(entry.claim.text, one_line=True)}{link} <!-- {CLAIM_MARK}{entry.claim.id} -->"


def render_report(
    *,
    report: Report,
    ctx: LineContext,
    claims: list[ClaimEntry],
    unjudged: list[str],
    operations: list[str],
) -> str:
    """`claims` in reading order (report.claims). `unjudged` / `operations` are display
    lines (sanitized here like everything else)."""
    body = (
        report.prose
        if report.prose is not None
        else ("本文生成なし (template)。受理された claim を以下に列挙する。")
    )
    parts = [
        _frontmatter(report, ctx, len(claims)),
        f"# {sanitize(ctx.line.name, one_line=True)} — {report.run_date.isoformat()}\n",
        sanitize(body) + "\n",
        "## Claims\n",
        "\n".join(claim_line(e) for e in claims) + ("\n" if claims else "(なし)\n"),
        "## 未判定\n",
        "\n".join(f"- {sanitize(u, one_line=True)}" for u in unjudged)
        + ("\n" if unjudged else "(なし)\n"),
        "## 運用\n",
        "\n".join(f"- {sanitize(o, one_line=True)}" for o in operations) + "\n",
    ]
    return "\n".join(parts)
