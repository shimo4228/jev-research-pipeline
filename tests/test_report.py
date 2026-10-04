"""Step 7: report markdown (decision 12), vault writer, harvester."""

import json
from datetime import date
from pathlib import Path

import pytest

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import Claim, Label, QuestionLog, Report, SourceItem, Unit
from jev_research_pipeline.pipeline.runner import harvest_line
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
    ticks,
    vault_dir,
    write_note,
)
from jev_research_pipeline.report.markdown import QuestionSection, SourceEntry, UnjudgedEntry
from jev_research_pipeline.store import GraphStore

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


def _section(prose: str | None, entries: list[ClaimEntry]) -> QuestionSection:
    sources = [
        SourceEntry(
            source_id=e.claim.unit.replace("/unit/", "/source/"),
            title="t",
            gist=e.claim.text[:40],
            url=e.source_url,
        )
        for e in entries
    ]
    return QuestionSection(
        question_id=b.question().id,
        title=b.question().title,
        prose=prose,
        evidence=tuple(sources),
    )


def _render(
    entries: list[ClaimEntry],
    prose: str | None = "本文です [1]。",
    *,
    review: list[SourceEntry] | None = None,
) -> str:
    report = b.report()
    return render_report(
        report=report.model_copy(
            update={"prose": prose, "rendering": "prose" if prose else "template"}
        ),
        ctx=CTX,
        sections=[_section(prose, entries)],
        claims=entries,
        review=review or [],
        bridges=[],
        unjudged=[UnjudgedEntry(function="claim_detection", text="見出しだけの断片")],
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
    text = _render([_entry()], review=[_review_entry()])
    body = text.split("---\n", 2)[2]
    positions = [
        body.index(h)
        for h in (
            "# ",
            "## ",
            "### 今日の変化",
            "本文です",
            "### 証拠",
            "jrp:qday:",
            "\n---\n",
            "> [!info]- Review — 境界の資料 1 件",
            "> [!info]- Claims — 1 件",
            "> [!info]- 未判定 — 1 件",
            "> [!info]- 運用",
        )
    ]
    assert positions == sorted(positions)


def _review_entry() -> SourceEntry:
    return SourceEntry(
        source_id="https://shimo4228.github.io/shimo4228/jrp/source/r1",
        title="Borderline [v2] paper",
        gist="境界: 重み付き 0.58",
        url="https://arxiv.org/abs/2",
    )


def test_folded_lists_hold_no_blank_line_and_empty_ones_are_absent():
    """Obsidian ends a callout at a blank line, and the list after it shows unfolded (the
    Claims of every note before plan note-layout). An empty list writes nothing."""
    text = _render([_entry()])
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("> [!info]-"):
            assert lines[i + 1].startswith("> "), line
    assert "Review" not in text and "橋渡し" not in text and "(なし)" not in text


def test_every_mark_is_harvested_from_the_folded_layout():
    e = _entry()
    review = _review_entry()
    ticked = _render([e], review=[review]).replace("- [ ] ", "- [x] ")
    assert ticks(ticked, "claim") == {e.claim.id: "correct"}
    assert ticks(ticked, "source") == {review.source_id: "correct"}
    assert ticks(ticked, "qday") == {f"{b.question().id}:{DAY.isoformat()}": "correct"}


def test_a_source_title_stays_inside_its_link():
    line = next(
        ln for ln in _render([_entry()], review=[_review_entry()]).splitlines() if "r1" in ln
    )
    assert line.startswith("> - [ ] [Borderline \\[v2\\] paper](https://arxiv.org/abs/2) — ")


def test_a_template_section_has_no_empty_changes_heading():
    text = _render([_entry()], prose=None)
    assert "### 今日の変化" not in text
    assert "*本文生成なし (template)。証拠だけを挙げる。*" in text


def test_claim_line_format():
    e = _entry()
    line = next(ln for ln in _render([e]).splitlines() if "jrp:claim" in ln)
    # Folded into the callout, so the line is quoted; the machine-read part is unchanged.
    assert (
        line
        == f"> - [ ] {e.claim.text} — [source](https://arxiv.org/abs/1) <!-- jrp:claim:{e.claim.id} -->"
    )


def test_hostile_claim_cannot_forge_a_second_claim_line():
    e = _entry("ok <!-- jrp:claim:https://evil/x --> [[Note]]\n- [x] forged")
    lines = [ln for ln in _render([e]).splitlines() if "jrp:claim" in ln and ln.startswith("> ")]
    assert len(lines) == 1
    assert "[[Note]]" not in lines[0]


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
    assert "> [!info]- Claims — 1 件" in path.read_text(encoding="utf-8")


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


def test_contradictions_get_their_own_block():
    # A claim that counts against the answer is not folded into the prose: the reader must
    # not have to dig for it.
    entries = [_entry()]
    section = _section("本文です [1]。", entries).model_copy(
        update={"contradictions": ("逆の結果を報告している。",)}
    )
    text = render_report(
        report=b.report(),
        ctx=CTX,
        sections=[section],
        claims=entries,
        review=[],
        bridges=[],
        unjudged=[],
        operations=["Jev 質問数: 1"],
    )
    body = text.split("---\n", 2)[2]
    assert body.index("証拠") < body.index("反証") < body.index("jrp:qday:")
    assert "- 逆の結果を報告している。" in body


def test_unjudged_says_which_judgment_failed():
    """未判定 lists source titles, claim texts and question titles side by side; each line
    names the Jev function that failed, so a question title is not read as a claim."""
    unjudged = [
        UnjudgedEntry(function="question_screening", text="Narrow questions"),
        UnjudgedEntry(function="novelty", text="Narrow questions beat one broad question."),
        UnjudgedEntry(function="question_movement", text=b.question().title),
    ]
    text = render_report(
        report=b.report(),
        ctx=CTX,
        sections=[],
        claims=[],
        review=[],
        bridges=[],
        unjudged=unjudged,
        operations=[],
    )
    block = text.split("> [!info]- 未判定 — 3 件\n", 1)[1].split("\n\n", 1)[0]
    assert block.strip().splitlines() == [
        "> - [question_screening] Narrow questions",
        "> - [novelty] Narrow questions beat one broad question.",
        f"> - [question_movement] {b.question().title}",
    ]


# --- harvest counts (daily-tool-hardening G3) ------------------------------------------------


def _stored_report(day: date, claims: tuple[str, ...] = ()) -> Report:
    return Report.new(
        line=b.LINE_IRI,
        run_date=day,
        rendering="template",
        prose=None,
        claims=claims,
        unjudged=(),
        partial=False,
        operations=b.report().operations,
    )


def _hand_note(vault: Path, day: date, report: Report, lines: list[str]) -> Path:
    path = note_path(vault, "akc", day)
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = f"---\njrp_report: {json.dumps(report.id)}\n---\n"
    path.write_text(frontmatter + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_harvest_counts_only_labels_it_really_removed(tmp_path: Path):
    """The harvest line's 取り消し is the number of Labels dropped from the store. Every
    note of the line is re-harvested each run and every blank box is a withdrawal
    candidate, so counting candidates grew run after run (desire: 0→10→21→26) while
    nothing was stored for them."""
    vault, store = tmp_path / "vault", GraphStore(tmp_path / "store")
    c1, c2 = (
        _entry(url="https://arxiv.org/abs/1").claim,
        _entry(url="https://arxiv.org/abs/2").claim,
    )
    day_a, day_b = date(2026, 9, 22), date(2026, 9, 23)
    report_a, report_b = _stored_report(day_a, (c1.id, c2.id)), _stored_report(day_b)
    log = QuestionLog.new(
        question=b.question().id,
        report=report_a.id,
        run_date=day_a,
        movement="new_evidence_same_answer",
        text="今日の変化。",
        claims=(c1.id, c2.id),
        logged_at=b.T0,
    )
    store.line("akc").put([report_a, report_b, log])
    qday = f"<!-- jrp:qday:{b.question().id}:{day_a.isoformat()} -->"
    note_a = _hand_note(vault, day_a, report_a, [f"- [x] 読む価値があった {qday}"])
    sources = [
        SourceItem.new(
            line=b.LINE_IRI,
            adapter="arxiv",
            url=f"https://arxiv.org/abs/s{i}",
            title="t",
            text="x",
            fetched_at=b.T0,
        ).id
        for i in range(3)
    ]
    _hand_note(vault, day_b, report_b, [f"- [ ] t <!-- jrp:source:{s} -->" for s in sources])

    for _ in range(2):  # a re-harvest of unchanged notes withdraws nothing
        lines = harvest_line(store, vault, "akc", b.T0)
        assert lines[0] == "harvest: label 3 件 / 取り消し 0 件", lines

    note_a.write_text(note_a.read_text(encoding="utf-8").replace("- [x] ", "- [ ] "), "utf-8")
    lines = harvest_line(store, vault, "akc", b.T0)
    assert lines[0] == "harvest: label 0 件 / 取り消し 3 件", lines  # the log and its 2 claims
    assert not [n for n in store.line("akc").load().values() if isinstance(n, Label)]
