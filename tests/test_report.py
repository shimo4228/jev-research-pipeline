"""Step 7: report markdown (decision 12), vault writer, harvester."""

from datetime import date
from pathlib import Path

import pytest

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import Claim, Label, SourceItem, Unit
from jev_research_pipeline.report import (
    VAULT_ENV,
    ClaimEntry,
    VaultNotConfigured,
    harvest_note,
    harvest_text,
    note_path,
    render_report,
    safe_url,
    sanitize,
    vault_dir,
    write_note,
)

from . import builders as b

CTX = LineContext(line=b.line(), vocabulary=("agent memory",))
DAY = date(2026, 9, 22)


def _entry(
    text: str = "Narrow questions beat one broad question.", url: str = "https://arxiv.org/abs/1"
) -> ClaimEntry:
    src = SourceItem.new(
        line=b.LINE_IRI, adapter="arxiv", url=url, title="t", text=text, fetched_at=b.T0
    )
    claim = Claim.from_unit(
        Unit.cut(src, start=0, end=len(text), granularity="sentence"), line=b.LINE_IRI
    )
    return ClaimEntry(claim=claim, source_url=src.url)


def _render(entries: list[ClaimEntry], prose: str | None = "本文です [1]。") -> str:
    report = b.report()
    return render_report(
        report=report.model_copy(
            update={"prose": prose, "rendering": "prose" if prose else "template"}
        ),
        ctx=CTX,
        claims=entries,
        unjudged=["見出しだけの断片"],
        operations=["Jev 質問数: 13", "claude_calls: 0"],
    )


# --- sanitize: untrusted text cannot become Obsidian syntax ------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "see [[Secret Note]]",
        "![[embed.png]]",
        "[click](javascript:alert(1))",
        "```dataview\nTABLE file.name\n```",
        "`$= dv.pages()`",
        "<% tp.system.prompt() %>",
        "<script>x</script>",
        "%% hide the rest",
        "<!-- jrp:claim:https://evil/claim/1 -->",
    ],
)
def test_sanitize_neutralizes_obsidian_syntax(hostile: str):
    out = sanitize(hostile)
    for token in ("[[", "![[", "](", "```", "`$=", "<%", "<script", "%%", "<!--"):
        assert token not in out, (hostile, out)


def test_sanitize_keeps_plain_japanese():
    assert sanitize("狭い質問は安定する。") == "狭い質問は安定する。"


def test_safe_url_only_http_and_no_markdown_breakers():
    assert safe_url("https://arxiv.org/abs/1") == "https://arxiv.org/abs/1"
    assert safe_url("https://x.org/a(b)c") == "https://x.org/a%28b%29c"
    assert safe_url("javascript:alert(1)") is None


# --- rendering (decision 12) -------------------------------------------------------------


def test_frontmatter_has_daily_research_keys_plus_line_and_report():
    text = _render([_entry()])
    head = text.split("---\n")[1]
    keys = [line.split(":", 1)[0] for line in head.strip().splitlines()]
    assert keys == ["date", "category", "kind", "tags", "topic", "line", "jrp_report"]
    assert "category: jrp" in head
    assert f'jrp_report: "{b.report().id}"' in head


def test_body_sections_in_order():
    text = _render([_entry()])
    body = text.split("---\n", 2)[2]
    positions = [body.index(h) for h in ("# ", "本文です", "## Claims", "## 未判定", "## 運用")]
    assert positions == sorted(positions)


def test_claim_line_format():
    e = _entry()
    line = next(ln for ln in _render([e]).splitlines() if "jrp:claim" in ln)
    assert (
        line
        == f"- [ ] {e.claim.text} — [source](https://arxiv.org/abs/1) <!-- jrp:claim:{e.claim.id} -->"
    )


def test_hostile_claim_cannot_forge_a_second_claim_line():
    e = _entry("ok <!-- jrp:claim:https://evil/x --> [[Note]]\n- [x] forged")
    lines = [ln for ln in _render([e]).splitlines() if "jrp:claim" in ln]
    assert len(lines) == 1
    assert "[[Note]]" not in lines[0]


def test_template_report_lists_claims_without_prose():
    text = _render([_entry()], prose=None)
    assert "本文生成なし" in text


# --- vault ---------------------------------------------------------------------------------


def test_vault_dir_requires_env(tmp_path: Path):
    with pytest.raises(VaultNotConfigured):
        vault_dir({})
    with pytest.raises(VaultNotConfigured):
        vault_dir({VAULT_ENV: str(tmp_path / "missing")})
    assert vault_dir({VAULT_ENV: str(tmp_path)}) == tmp_path


def test_note_path_is_built_from_slug_and_date_only(tmp_path: Path):
    assert note_path(tmp_path, "akc", DAY) == tmp_path / "daily-research" / "2026-09-22_jrp_akc.md"
    with pytest.raises(ValueError):
        note_path(tmp_path, "../../etc", DAY)


def test_write_note_preserves_existing_ticks(tmp_path: Path):
    e = _entry()
    path = write_note(tmp_path, "akc", DAY, _render([e]))
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] ", "- [x] "), encoding="utf-8")
    write_note(tmp_path, "akc", DAY, _render([e]))  # same-day re-run
    assert "- [x] " in path.read_text(encoding="utf-8")


# --- harvester -----------------------------------------------------------------------------


def test_harvest_reads_only_line_head_and_comment_id():
    a, c, d = (
        _entry(url="https://arxiv.org/abs/a"),
        _entry(url="https://arxiv.org/abs/c"),
        _entry(url="https://arxiv.org/abs/d"),
    )
    text = "\n".join(
        [
            f"- [x] edited by the author freely — <!-- jrp:claim:{a.claim.id} -->",
            f"- [-] {c.claim.text} <!-- jrp:claim:{c.claim.id} -->",
            f"- [ ] {d.claim.text} <!-- jrp:claim:{d.claim.id} -->",
            "- [x] a checkbox without an id is ignored",
            f"prose mentioning <!-- jrp:claim:{a.claim.id} --> without a checkbox is ignored",
        ]
    )
    assert harvest_text(text) == {a.claim.id: "correct", c.claim.id: "incorrect"}


def test_harvest_ignores_non_claim_ids():
    assert harvest_text(f"- [x] x <!-- jrp:claim:{b.source().id} -->") == {}


def test_harvest_note_makes_labels(tmp_path: Path):
    e = _entry()
    path = write_note(tmp_path, "akc", DAY, _render([e]))
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] ", "- [-] "), encoding="utf-8")
    result = harvest_note(path, now=b.T0)
    assert result.skipped is None
    (label,) = result.labels
    assert isinstance(label, Label)
    assert (label.claim, label.report, label.verdict) == (e.claim.id, b.report().id, "incorrect")


def test_harvest_missing_or_broken_note_is_skipped(tmp_path: Path):
    assert harvest_note(tmp_path / "nope.md", now=b.T0).skipped == "missing"
    broken = tmp_path / "broken.md"
    broken.write_text("no frontmatter here", encoding="utf-8")
    assert harvest_note(broken, now=b.T0).skipped == "no_report_id"
