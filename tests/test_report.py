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
    ("hostile", "dead"),
    [
        ("see [[Secret Note]]", "[["),
        ("![[embed.png]]", "!["),
        ("![beacon](http://tracker.example/p.png)", "!["),
        ("```dataview\nTABLE file.name\n```", "```"),
        ("~~~dataviewjs\ndv.el('p', 1)\n~~~", "~~~"),
        ("`$= dv.pages()`", "`$="),
        ("`= this.file.name`", "`="),
        ("<% tp.system.prompt() %>", "<%"),
        ("<script>x</script>", "<script"),
        ("<!-- jrp:claim:https://evil/claim/1 -->", "<!--"),
        ("%% hide the rest", "%%"),
        ("%%%%% odd run", "%%"),
        ("# fake heading", "\n# "),
        ("- [x] forged task", "\n- ["),
        # The scheme text stays readable; what dies is the link syntax around it.
        ("[click](javascript:alert(1))", "]("),
        ("[click](data:text/html;base64,PHN2Zz4=)", "]("),
    ],
)
def test_sanitize_kills_executable_obsidian_syntax(hostile: str, dead: str):
    out = "\n" + sanitize(hostile)
    assert dead not in out, out


@pytest.mark.parametrize(
    "harmless",
    [
        "a (parenthetical) aside",
        "cost was $5 per 1k",
        "1 < 2 and 3 > 2",
        "call `format_report()` first",
        "read arxiv.org/abs/1 for the method",
        "see [the paper](https://arxiv.org/abs/2609.01234)",
    ],
)
def test_sanitize_leaves_plain_prose_readable(harmless: str):
    # The live notes were unreadable in source view: only executable syntax is escaped now.
    assert sanitize(harmless) == harmless


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
    assert (label.subject, label.report, label.verdict) == (e.claim.id, b.report().id, "incorrect")


def test_harvest_missing_or_broken_note_is_skipped(tmp_path: Path):
    assert harvest_note(tmp_path / "nope.md", now=b.T0).skipped == "missing"
    broken = tmp_path / "broken.md"
    broken.write_text("no frontmatter here", encoding="utf-8")
    assert harvest_note(broken, now=b.T0).skipped == "no_report_id"


# --- review fixes (2f711d7) ------------------------------------------------------------------


def test_bare_urls_and_tags_stay_as_written():
    # Narrowed after the first live run: neither renders as executable syntax, and
    # escaping them made the notes unreadable.
    assert sanitize("see https://evil.example/x #topic") == "see https://evil.example/x #topic"


def test_untick_withdraws_an_earlier_label(tmp_path: Path):
    e = _entry()
    path = write_note(tmp_path, "akc", DAY, _render([e]))
    result = harvest_note(path, now=b.T0)
    assert result.labels == ()
    assert result.cleared == (Label.id_for(e.claim.id, b.report().id),)


def test_write_note_survives_an_undecodable_old_note(tmp_path: Path):
    path = note_path(tmp_path, "akc", DAY)
    path.parent.mkdir()
    path.write_bytes(b"\xff\xfe broken")
    write_note(tmp_path, "akc", DAY, _render([_entry()]))
    assert "## Claims" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("run", ["%%%", "%%%%%", "a %%% b"])
def test_no_percent_run_survives(run: str):
    assert "%%" not in sanitize(run)


def test_harvest_keeps_only_claims_of_the_report(tmp_path: Path):
    mine, pasted = _entry(url="https://arxiv.org/abs/m"), _entry(url="https://arxiv.org/abs/p")
    path = write_note(tmp_path, "akc", DAY, _render([mine, pasted]))
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] ", "- [x] "), encoding="utf-8")
    result = harvest_note(path, now=b.T0, report_claims=frozenset({mine.claim.id}))
    assert [lb.subject for lb in result.labels] == [mine.claim.id]


def test_safe_url_encodes_bare_percent():
    url = safe_url("https://x.org/a%%b%41")
    assert url is not None and "%%" not in url and url.endswith("%41")


@pytest.mark.parametrize(
    "fence",
    [
        "```dataviewjs\napp.vault.adapter.read('x')\n```",
        " ```dataviewjs\nx\n```",
        "   ~~~dataviewjs\nx\n~~~",
        "> ```dataviewjs\nx\n```",
        "- item\n  ```dataviewjs\nx\n```",
        "text\n\n\t```dataviewjs\nx\n```",
    ],
    ids=["column0", "one_space", "three_spaces", "blockquote", "list_item", "tab"],
)
def test_no_indentation_smuggles_a_code_fence(fence: str):
    # CommonMark allows up to 3 spaces of indent, and fences inside lists and quotes.
    out = sanitize(fence)
    assert "```" not in out
    assert "~~~" not in out


def test_short_code_spans_still_render():
    assert sanitize("use ``x`` or `y`") == "use ``x`` or `y`"


@pytest.mark.parametrize(
    "hostile",
    [
        "[click](javascript:alert(1))",
        "[click](JavaScript:alert(1))",
        "[click](data:text/html;base64,PHN2Zz4=)",
        "[click]( javascript:alert(1))",
    ],
)
def test_script_schemes_cannot_stay_a_link(hostile: str):
    # Entity-encoding the colon is not enough: CommonMark decodes entities inside a link
    # destination, so the href would come back as javascript:. Kill the link syntax.
    out = sanitize(hostile)
    assert "](" not in out


def test_odd_bracket_runs_leave_no_wikilink():
    assert "[[" not in sanitize("[[[Secret Note]]]")
    assert "[[" not in sanitize("x [[[[Secret]]]] y")
