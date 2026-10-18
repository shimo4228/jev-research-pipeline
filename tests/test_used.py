"""Used rate (plan used-rate-label): a delayed label measured beside the ticks. It is a
measurement only, so the tests pin both halves: the verdicts, and that nothing else reads a
UsedMark or loses a Label because of one."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jev_research_pipeline import note_text as t
from jev_research_pipeline.model import (
    Label,
    Question,
    QuestionLog,
    Sighting,
    SourceItem,
    UsedMark,
)
from jev_research_pipeline.pipeline.config import TrackSpec
from jev_research_pipeline.pipeline.runner import harvest_line, run_pipeline, update_used
from jev_research_pipeline.reduction import DecisionLog, used
from jev_research_pipeline.reduction.used import (
    STARTED_KEY,
    WINDOW_DAYS,
    Scan,
    UsedRate,
    is_jrp_output,
    keys_of_text,
    mark_used,
    record_sightings,
    scan_documents,
    unread_paths,
    verdict_of,
)
from jev_research_pipeline.store import GraphStore, Partition

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_world
from .test_e2e import env as env

D0 = date(2026, 9, 22)


# --- keys -------------------------------------------------------------------------------


def test_keys_come_from_ids_and_normalized_urls_only():
    text = (
        "See arXiv:2610.21411v2 and https://arxiv.org/pdf/2609.00001.pdf, "
        "https://huggingface.co/papers/2608.12345 (doi: 10.1145/3580305.3599330). "
        "Code: https://www.github.com/Foo/Bar.git?tab=readme#top and https://Example.org/A/b/."
    )
    assert keys_of_text(text) >= {
        "arxiv:2610.21411",
        "arxiv:2609.00001",
        "arxiv:2608.12345",
        "doi:10.1145/3580305.3599330",
        "gh:foo/bar",
        "url:example.org/a/b",
        "url:github.com/foo/bar.git?tab=readme",
    }


def test_a_bare_number_or_a_title_is_not_a_key():
    assert keys_of_text("version 2024.1234 of the paper 'Narrow questions' (2013.00001)") == set()


def test_an_arxiv_doi_is_both_a_doi_and_an_arxiv_key():
    assert {"arxiv:2610.21411", "doi:10.48550/arxiv.2610.21411"} <= keys_of_text(
        "https://doi.org/10.48550/arXiv.2610.21411"
    )


def test_a_source_url_and_the_text_that_cites_it_share_a_key():
    cited = keys_of_text("[paper](https://arxiv.org/abs/2609.00001v3)")
    assert keys_of_text(b.source().url) & cited == {"arxiv:2609.00001"}


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("2026-10-01_jrp_akc.md", "x", True),
        ("note.md", '---\ncategory: jrp\njrp_report: "https://x/jrp/report/1"\n---\n', True),
        ("note.md", "- [ ] t <!-- jrp:source:https://x -->", True),
        ("2026-09-22_akc_memory.md", "an old pipeline note", False),
    ],
)
def test_jrp_output_is_recognized(path: str, text: str, expected: bool):
    assert is_jrp_output(Path(path), text) is expected


# --- scanning the author's documents ---------------------------------------------------


def _documents(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    (repo / "docs" / "adr").mkdir(parents=True)
    graph = {"@graph": [{"@id": "x", "sameAs": "https://arxiv.org/abs/2601.00001"}]}
    (repo / "graph.jsonld").write_text(json.dumps(graph).replace("/", "\\/"), encoding="utf-8")
    (repo / "docs" / "adr" / "0001.md").write_text("Based on arXiv:2602.00002.", encoding="utf-8")
    vault = tmp_path / "vault"
    (vault / "daily-research").mkdir(parents=True)
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "x.md").write_text("arXiv:2699.00001", encoding="utf-8")
    (vault / "mine.md").write_text(
        "arXiv:2603.00003 https://github.com/me/tool arXiv:2601.00001", encoding="utf-8"
    )
    (vault / "daily-research" / "2026-10-01_jrp_akc.md").write_text(
        "[t](https://arxiv.org/abs/2604.00004)", encoding="utf-8"
    )
    return repo, vault


def test_scan_reads_graph_adr_and_vault_but_not_jrp_notes_or_the_authors_owner(tmp_path: Path):
    repo, vault = _documents(tmp_path)
    found = scan_documents([repo, repo], vault, owner="Me").found
    assert found["arxiv:2601.00001"] == "graph"  # the first place that holds it
    assert found["arxiv:2602.00002"] == "adr"
    assert found["arxiv:2603.00003"] == "vault"  # a note at the vault root
    assert "arxiv:2604.00004" not in found  # a jrp note
    assert "arxiv:2699.00001" not in found  # .obsidian
    assert not [k for k in found if "me/tool" in k]  # the author's own repo


def test_a_query_tells_documents_apart_but_tracking_parameters_do_not():
    a = keys_of_text("https://www.youtube.com/watch?v=aaa&utm_source=x")
    assert a.isdisjoint(keys_of_text("https://youtube.com/watch?v=bbb"))
    assert keys_of_text("https://youtube.com/watch?utm_medium=m&v=aaa&fbclid=z") == {
        "url:youtube.com/watch?v=aaa"
    }
    assert keys_of_text("https://news.ycombinator.com/item?id=1") != keys_of_text(
        "https://news.ycombinator.com/item?id=2"
    )
    assert keys_of_text("https://x.org/p?b=2&a=1") == keys_of_text("https://x.org/p?a=1&b=2")


def test_the_vault_place_names_the_top_folder(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "wiki" / "deep").mkdir(parents=True)
    (vault / "wiki" / "deep" / "a.md").write_text("arXiv:2601.00001", encoding="utf-8")
    (vault / "daily-research").mkdir()
    (vault / "daily-research" / "b.md").write_text("arXiv:2602.00002", encoding="utf-8")
    found = scan_documents([], vault).found
    assert (found["arxiv:2601.00001"], found["arxiv:2602.00002"]) == (
        "vault:wiki",
        "vault:daily-research",
    )


def test_the_first_day_a_key_is_seen_wins_and_the_first_scan_is_the_baseline(tmp_path: Path):
    part = GraphStore(tmp_path / "store").pipeline()
    first = record_sightings(part, Scan(found={"arxiv:2601.00001": "vault"}), D0)
    assert first["arxiv:2601.00001"].baseline and first[STARTED_KEY].first_seen == D0

    later = record_sightings(
        part,
        Scan(found={"arxiv:2601.00001": "adr", "arxiv:2602.00002": "adr"}),
        D0 + timedelta(days=3),
    )
    assert later["arxiv:2601.00001"].first_seen == D0
    assert later["arxiv:2601.00001"].place == "vault"
    new = later["arxiv:2602.00002"]
    assert (new.first_seen, new.baseline) == (D0 + timedelta(days=3), False)
    assert len([n for n in part.load().values() if isinstance(n, Sighting)]) == 3


# --- verdicts ---------------------------------------------------------------------------


def _mark(surfaced: date = D0, observed: date | None = None) -> UsedMark:
    return UsedMark.new(
        source=b.source().id,
        report=b.report().id,
        surfaced_on=surfaced,
        observed_from=observed or surfaced,
        verdict="pending",
    )


def _seen(on: date, baseline: bool = False) -> Sighting:
    return Sighting.new(key="arxiv:2609.00001", first_seen=on, place="vault", baseline=baseline)


def _day(n: int) -> date:
    return D0 + timedelta(days=n)


@pytest.mark.parametrize(
    ("matching", "today", "observed", "expected"),
    [
        ([_seen(_day(5))], _day(5), D0, ("used", _day(5))),
        ([_seen(_day(WINDOW_DAYS))], _day(WINDOW_DAYS), D0, ("used", _day(WINDOW_DAYS))),
        ([], _day(WINDOW_DAYS - 1), D0, ("pending", None)),
        ([], _day(WINDOW_DAYS), D0, ("unused", None)),
        # Seen after the window closed: not within 30 days.
        ([_seen(_day(WINDOW_DAYS + 4))], _day(WINDOW_DAYS + 4), D0, ("unused", None)),
        # There before the source was surfaced, or the same day.
        ([_seen(_day(-3))], _day(1), D0, ("unknown", None)),
        ([_seen(D0)], _day(1), D0, ("unknown", None)),
        # In the first scan's index: it predates anything the scan could observe.
        ([_seen(_day(2), baseline=True)], _day(2), D0, ("unknown", None)),
        # The scan began inside the window: absence proves nothing.
        ([], _day(WINDOW_DAYS), _day(10), ("unknown", None)),
        ([_seen(_day(12))], _day(12), _day(10), ("used", _day(12))),
    ],
)
def test_verdicts(
    matching: list[Sighting], today: date, observed: date, expected: tuple[str, date | None]
):
    assert verdict_of(_mark(observed=observed), matching, today) == expected


def test_a_used_mark_says_when_it_was_seen_exactly_when_it_is_used():
    base = _mark().model_dump(by_alias=True, mode="json")
    with pytest.raises(ValidationError, match="seen_on"):
        UsedMark.model_validate({**base, "verdict": "used"})
    with pytest.raises(ValidationError, match="seen_on"):
        UsedMark.model_validate({**base, "verdict": "unused", "seen_on": "2026-09-23"})


# --- marks in a partition -----------------------------------------------------------------


def _partition(tmp_path: Path, *extra: Question) -> Partition:
    part = GraphStore(tmp_path / "store").line("akc")
    part.put([b.source(), b.question_log(), *extra])
    return part


def _marks(part: Partition) -> list[UsedMark]:
    return [n for n in part.load().values() if isinstance(n, UsedMark)]


def test_a_source_is_pending_then_used_when_its_key_turns_up_in_the_window(tmp_path: Path):
    part = _partition(tmp_path)
    pipeline = GraphStore(tmp_path / "store").pipeline()
    # The log is from 2026-09-22; the scan began the day before, so the window is fully seen.
    mark_used(
        part, record_sightings(pipeline, Scan(), b.T0.date() - timedelta(days=1)), b.T0.date()
    )
    (mark,) = _marks(part)
    assert (mark.verdict, mark.surfaced_on, mark.observed_from) == (
        "pending",
        b.T0.date(),
        b.T0.date(),
    )

    later = b.T0.date() + timedelta(days=9)
    sightings = record_sightings(pipeline, Scan(found={"arxiv:2609.00001": "adr"}), later)
    assert mark_used(part, sightings, later) == 1
    (mark,) = _marks(part)
    assert (mark.verdict, mark.seen_on) == ("used", later)

    # A settled mark is left alone, even when the key is gone from the documents.
    assert (
        mark_used(part, record_sightings(pipeline, Scan(), later), later + timedelta(days=60)) == 0
    )
    assert UsedRate(_marks(part)).rate == 1.0


def test_a_source_that_was_not_seen_is_unused_and_nothing_else(tmp_path: Path):
    part = _partition(tmp_path)
    pipeline = GraphStore(tmp_path / "store").pipeline()
    sightings = record_sightings(pipeline, Scan(), b.T0.date() - timedelta(days=1))
    mark_used(part, sightings, b.T0.date())
    mark_used(part, sightings, b.T0.date() + timedelta(days=WINDOW_DAYS))
    (mark,) = _marks(part)
    assert mark.verdict == "unused"
    rate = UsedRate(_marks(part))
    assert (rate.used, rate.unused, rate.rate) == (0, 1, 0.0)
    # Not a negative: no Label was made, and the gold stays what the author ticked.
    assert not [n for n in part.load().values() if isinstance(n, Label)]
    assert DecisionLog.from_partition(part).gold() == {}


def test_a_source_surfaced_before_the_scan_began_is_unknown_when_absent(tmp_path: Path):
    part = _partition(tmp_path)
    pipeline = GraphStore(tmp_path / "store").pipeline()
    on = b.T0.date() + timedelta(days=5)  # the first scan, five days after the surfacing
    sightings = record_sightings(pipeline, Scan(), on)
    mark_used(part, sightings, on)
    mark_used(part, sightings, b.T0.date() + timedelta(days=WINDOW_DAYS))
    (mark,) = _marks(part)
    assert (mark.verdict, mark.observed_from) == ("unknown", on)
    assert UsedRate(_marks(part)).rate is None


def test_a_canary_paper_is_never_counted(tmp_path: Path):
    canary = Question.new(
        line=b.LINE_IRI,
        slug="agent-memory",
        version=1,
        title="q",
        opened_at=b.T0,
        canary_papers=(b.source().url,),
    )
    part = _partition(tmp_path, canary)
    mark_used(part, record_sightings(GraphStore(tmp_path / "store").pipeline(), Scan(), D0), D0)
    assert _marks(part) == []


def test_a_blank_box_does_not_withdraw_a_used_mark(tmp_path: Path):
    """The reason for a node type of its own: a Label with the same @id would be dropped by
    the harvest of an empty box."""
    part = _partition(tmp_path)
    store = GraphStore(tmp_path / "store")
    sightings = record_sightings(store.pipeline(), Scan(), b.T0.date() - timedelta(days=1))
    mark_used(part, sightings, b.T0.date())
    vault = tmp_path / "vault"
    (vault / "daily-research").mkdir(parents=True)
    report = b.report()
    (vault / "daily-research" / "2026-09-22_jrp_akc.md").write_text(
        f'---\ncategory: jrp\njrp_report: "{report.id}"\n---\n'
        f"- [ ] t <!-- jrp:source:{b.source().id} -->\n",
        encoding="utf-8",
    )
    part.put([report])
    harvest_line(store, vault, "akc", b.T0)
    assert len(_marks(part)) == 1


# --- the run ------------------------------------------------------------------------------


def test_update_used_reads_every_tracks_repo_and_survives_a_bad_store(tmp_path: Path):
    repo, vault = _documents(tmp_path)
    store = GraphStore(tmp_path / "store")
    track = TrackSpec(slug="akc", name="akc", repo=repo, daily=False)
    store.line("akc").put([b.source(), b.question_log()])
    notes, scan = update_used(store, [track], vault, ["akc"], b.T0)
    assert notes == [] and scan is not None and not scan.unread
    keys = {n.key for n in store.pipeline().load().values() if isinstance(n, Sighting)}
    assert {"arxiv:2601.00001", "arxiv:2602.00002", "arxiv:2603.00003", STARTED_KEY} <= keys

    (tmp_path / "store" / "pipeline.jsonld").write_text("{not json", encoding="utf-8")
    (skip,), none = update_used(store, [track], vault, ["akc"], b.T0)
    assert none is None
    assert skip.startswith("used skip: ")


async def test_the_note_gets_a_used_rate_line_and_the_ticks_stay(
    cassette: ClientFactory, env: dict[str, str]
):
    http = cassette(fake_world())
    (outcome,) = await run_pipeline(env, now=b.T0, http=http, pacing=False)
    text = outcome.note.read_text(encoding="utf-8")
    assert "記入率 (前回): なし" in text
    assert "used rate (30 日): 測定中 (窓が閉じたソース 0 件 · 待機 0 · 判定不能 0)" in text

    part = GraphStore(Path(env["JRP_STORE_DIR"])).line("akc")
    assert not _marks(part)  # the surfaced sources get their marks on the next run

    next_day = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)
    await run_pipeline(env, now=next_day, http=cassette(fake_world()), pacing=False)
    logs = [n for n in part.load().values() if isinstance(n, QuestionLog)]
    surfaced = {s for log in logs if log.run_date == b.T0.date() for s in log.sources}
    assert surfaced
    assert surfaced <= {m.source for m in _marks(part)}
    assert {m.verdict for m in _marks(part)} <= {"pending", "unknown"}
    assert {n.id for n in part.load().values() if isinstance(n, SourceItem)} >= surfaced


# --- files the scan could not read ------------------------------------------------------


def test_a_jrp_note_is_decided_by_its_name_and_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "2026-10-01_jrp_akc.md").write_text("arXiv:2604.00004", encoding="utf-8")
    opened: list[str] = []
    real = Path.read_text

    def spy(self: Path, *a: Any, **k: Any) -> str:
        opened.append(self.name)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    scan = scan_documents([], vault)
    assert opened == [] and scan.found == {} and scan.unread == set()


def test_a_dataless_file_is_skipped_unread_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault = tmp_path / "vault"
    vault.mkdir()
    cold = vault / "cold.md"
    cold.write_text("arXiv:2601.00001", encoding="utf-8")
    (vault / "warm.md").write_text("arXiv:2602.00002", encoding="utf-8")
    real_stat, real_read = Path.stat, Path.read_text

    class ColdStat:
        st_size = 10
        st_flags = used.DATALESS

    def fake_stat(self: Path, *a: Any, **k: Any) -> Any:
        return ColdStat() if self.name == "cold.md" else real_stat(self, *a, **k)

    def guarded_read(self: Path, *a: Any, **k: Any) -> str:
        assert self.name != "cold.md", "a dataless file must not be opened"
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "stat", fake_stat)
    monkeypatch.setattr(Path, "read_text", guarded_read)
    scan = scan_documents([], vault)
    assert scan.unread == {str(cold)} and not scan.capped
    assert set(scan.found) == {"arxiv:2602.00002"}


def test_the_scan_stops_at_its_time_cap_and_says_so(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    for i in range(5):
        (vault / f"n{i}.md").write_text(f"arXiv:260{i + 1}.00001", encoding="utf-8")
    ticks = iter(range(100))
    scan = scan_documents([], vault, budget=2.5, clock=lambda: float(next(ticks)))
    assert scan.capped and scan.unread
    assert len(scan.unread) + len(scan.found) == 5  # every file is read or counted


def test_scan_taints_keys_found_in_a_previously_unread_file(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "a.md"
    note.write_text("arXiv:2601.00001", encoding="utf-8")
    (vault / "b.md").write_text("arXiv:2602.00002", encoding="utf-8")
    scan = scan_documents([], vault, prior_unread={str(note)})
    assert scan.tainted == {"arxiv:2601.00001"}


def test_a_key_first_seen_in_a_file_the_scan_before_could_not_read_is_never_used(tmp_path: Path):
    part = _partition(tmp_path)
    pipeline = GraphStore(tmp_path / "store").pipeline()
    cold = "/vault/cold.md"
    # The first scan could not read cold.md.
    record_sightings(pipeline, Scan(unread={cold}), b.T0.date() - timedelta(days=1))
    assert unread_paths(pipeline) == {cold}
    # Later cold.md is downloaded and holds the surfaced source's key.
    scan = Scan(found={"arxiv:2609.00001": "vault:wiki"}, tainted={"arxiv:2609.00001"})
    day3 = b.T0.date() + timedelta(days=3)
    sightings = record_sightings(pipeline, scan, day3)
    assert sightings["arxiv:2609.00001"].unsure
    assert unread_paths(pipeline) == set()  # the marker went with the read
    mark_used(part, sightings, day3)
    (mark,) = _marks(part)
    assert mark.verdict == "unknown"


def test_the_used_rate_line_shows_unread_files_and_the_cap():
    assert t.USED_UNREAD("ja", n=467).startswith(" · 未読 467 件")
    assert "30 s cap" in t.USED_CAPPED("en", seconds="30")
