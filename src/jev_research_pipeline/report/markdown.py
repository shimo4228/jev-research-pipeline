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
wikilink / embed / link / HTML / code fence / Dataview or Templater expression — and it
must never be able to forge a `<!-- jrp:claim -->` line. Source URLs pass through
safe_url() (http(s) only, markdown-breaking characters percent-encoded).
"""

import json
from typing import Final
from urllib.parse import quote

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import Claim, Report
from jev_research_pipeline.model.jsonld import Value

CATEGORY: Final = "jrp"
KIND: Final = "report"
CLAIM_MARK: Final = "jrp:claim:"

# Order matters: the backslash first, so later escapes are not double-escaped.
_ESCAPES: Final = (
    ("\\", "\\\\"),
    ("`", "\\`"),
    ("$", "\\$"),
    ("[", "\\["),
    ("]", "\\]"),
    ("(", "\\("),
    (")", "\\)"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ("%%", "%\\%"),
)


class ClaimEntry(Value):
    claim: Claim
    source_url: str


def sanitize(text: str, *, one_line: bool = False) -> str:
    """Untrusted text → inert markdown text."""
    out = text
    for raw, escaped in _ESCAPES:
        out = out.replace(raw, escaped)
    return " ".join(out.split()) if one_line else out


def safe_url(url: str) -> str | None:
    """http(s) URL with markdown-breaking characters percent-encoded; None for anything else."""
    if not url.startswith(("https://", "http://")):
        return None
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
