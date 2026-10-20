"""Opened (plan quality-metrics, author decision 2026-10-20): which jrp notes the author
opened, read from Obsidian's recently-opened lists as the wrapper stages them. Only jrp
note names and the first day each was seen are ever stored; everything else on the list
is dropped, and a list jrp cannot read is no name rather than an error."""

import json
from datetime import date
from pathlib import Path

import httpx2
import pytest
from pydantic import JsonValue

from jev_research_pipeline.pipeline.runner import run_pipeline, update_opened
from jev_research_pipeline.reduction.opened import (
    OPENED_FILE,
    first_seen,
    jrp_notes,
    line_note,
    opened_notes,
    record_opened,
    recorded,
)
from jev_research_pipeline.store import GraphStore
from jev_research_pipeline.store.migrate import partition_files, prepare_store

from . import builders as b
from .fakes import fake_world
from .test_e2e import env as env  # the fixture, re-exported

AKC = "daily-research/2026-10-20_jrp_akc.md"
EDGE = "daily-research/2026-10-19_jrp_edge.md"
DEEP = b'{"lastOpenFiles": ' + b"[" * 100_000 + b"]" * 100_000 + b"}"
"""Nested past what json.loads can recurse into: it raises RecursionError, not ValueError."""


def _workspace(vault: Path, *files: str, name: str = "workspace.json") -> Path:
    """An Obsidian workspace file with these entries on its recently-opened list."""
    path = vault / ".obsidian" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    listed: list[JsonValue] = list(files)
    doc: dict[str, JsonValue] = {"main": {}, "left": {}, "right": {}, "lastOpenFiles": listed}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _rows(store: Path) -> list[dict[str, str]]:
    return [json.loads(ln) for ln in (store / OPENED_FILE).read_text("utf-8").splitlines()]


def test_only_jrp_notes_directly_in_daily_research_are_kept():
    entries: list[JsonValue] = [
        AKC,
        "daily-research/2026-10-20_edge_other.md",  # not a jrp note
        "notes/2026-10-20_jrp_akc.md",  # another folder
        "daily-research/old/2026-09-01_jrp_akc.md",  # a sub-folder
        "daily-research/2026-10-20_jrp_akc.pdf",
        "2026-10-20_jrp_akc.md",  # the vault root
        "Journal/2026-10-20 private.md",
        "daily-research/2026-10-26_jrp_wbr.md",  # the weekly review's own note
        3,
        None,
        {"path": AKC},
    ]
    assert jrp_notes(entries) == {"2026-10-20_jrp_akc.md"}


@pytest.mark.parametrize(
    ("name", "kept"),
    [
        ("2026-10-20_jrp_akc.md", True),
        ("2026-10-20_jrp_wbr-notes.md", True),  # a slug that starts like the reserved one
        ("2026-10-26_jrp_wbr.md", False),
        ("x_jrp_y_jrp_wbr.md", False),  # the slug is what follows the last _jrp_
        ("2026-10-26_jrp_wbr.md.bak", False),
        ("2026-10-20_akc.md", False),
    ],
)
def test_a_line_note_is_a_jrp_note_of_an_unreserved_slug(name: str, kept: bool):
    assert line_note(name) is kept


def test_both_lists_are_read_and_nothing_else_of_obsidian(tmp_path: Path):
    _workspace(tmp_path, AKC, "Journal/private.md")
    _workspace(tmp_path, EDGE, name="workspace-mobile.json")
    _workspace(tmp_path, "daily-research/2026-10-18_jrp_ans.md", name="workspace 2.json")
    _workspace(tmp_path, "daily-research/2026-10-17_jrp_ans.md", name="app.json")
    assert opened_notes(tmp_path) == {"2026-10-20_jrp_akc.md", "2026-10-19_jrp_edge.md"}


@pytest.mark.parametrize(
    "raw",
    [
        b"{not json",
        b"\xff\xfe not utf-8",
        b"[]",
        b'"lastOpenFiles"',
        b'{"main": {}}',
        b'{"lastOpenFiles": "daily-research/2026-10-20_jrp_akc.md"}',
        b'{"lastOpenFiles": null}',
        DEEP,
    ],
    ids=["not_json", "not_utf8", "array", "string", "no_list", "list_is_str", "null", "deep"],
)
def test_a_list_jrp_cannot_read_is_no_name_not_an_error(tmp_path: Path, raw: bytes):
    path = tmp_path / ".obsidian" / "workspace.json"
    path.parent.mkdir()
    path.write_bytes(raw)
    _workspace(tmp_path, EDGE, name="workspace-mobile.json")  # the other one still counts
    assert opened_notes(tmp_path) == {"2026-10-19_jrp_edge.md"}


def test_a_vault_without_obsidian_records_nothing_and_creates_nothing(tmp_path: Path):
    store = tmp_path / "store"
    assert record_opened(tmp_path / "vault", store, date(2026, 10, 20)) == 0
    assert not store.exists()


def test_a_name_is_recorded_once_with_the_day_it_was_first_seen(tmp_path: Path):
    vault, store = tmp_path / "vault", tmp_path / "store"
    _workspace(vault, EDGE, AKC, "Journal/private.md")
    assert record_opened(vault, store, date(2026, 10, 20)) == 2
    assert (store / OPENED_FILE).read_text("utf-8") == (
        '{"note": "2026-10-19_jrp_edge.md", "first_seen": "2026-10-20"}\n'
        '{"note": "2026-10-20_jrp_akc.md", "first_seen": "2026-10-20"}\n'
    )
    assert "private" not in (store / OPENED_FILE).read_text("utf-8")

    _workspace(vault, "daily-research/2026-10-21_jrp_akc.md", AKC)  # the next morning
    assert record_opened(vault, store, date(2026, 10, 21)) == 1
    assert record_opened(vault, store, date(2026, 10, 22)) == 0  # nothing new
    assert _rows(store) == [
        {"note": "2026-10-19_jrp_edge.md", "first_seen": "2026-10-20"},
        {"note": "2026-10-20_jrp_akc.md", "first_seen": "2026-10-20"},
        {"note": "2026-10-21_jrp_akc.md", "first_seen": "2026-10-21"},
    ]


def test_a_line_cut_short_neither_blocks_nor_swallows_the_next_one(tmp_path: Path):
    vault, store = tmp_path / "vault", tmp_path / "store"
    (store / OPENED_FILE).parent.mkdir(parents=True)
    (store / OPENED_FILE).write_text(
        '{"note": "2026-10-19_jrp_edge.md", "first_seen": "2026-10-19"}\n'
        '{"first_seen": "2026-10-19"}\n["2026-10-20_jrp_akc.md"]\n{"note": "2026-1',
        encoding="utf-8",
    )
    assert recorded((store / OPENED_FILE).read_text("utf-8")) == {"2026-10-19_jrp_edge.md"}
    _workspace(vault, EDGE, AKC)
    assert record_opened(vault, store, date(2026, 10, 20)) == 1
    lines = (store / OPENED_FILE).read_text("utf-8").splitlines()
    assert lines[3] == '{"note": "2026-1'  # left as it was
    assert json.loads(lines[4]) == {"note": "2026-10-20_jrp_akc.md", "first_seen": "2026-10-20"}


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85"])
def test_a_name_with_a_line_separator_in_it_is_recorded_once(tmp_path: Path, separator: str):
    """json.dumps(ensure_ascii=False) writes these raw, and str.splitlines() would cut the
    row there: the name would never read back as recorded and be appended every run."""
    vault, store = tmp_path / "vault", tmp_path / "store"
    odd = f"daily-research/2026-10-20_jrp_a{separator}b.md"
    _workspace(vault, odd)
    assert record_opened(vault, store, date(2026, 10, 20)) == 1
    assert record_opened(vault, store, date(2026, 10, 21)) == 0
    text = (store / OPENED_FILE).read_text("utf-8")
    assert recorded(text) == {f"2026-10-20_jrp_a{separator}b.md"}
    assert len(text.split("\n")) == 2  # one row and the empty tail


def test_first_seen_keeps_each_names_earliest_day_and_skips_what_it_cannot_read():
    """What the weekly review's registry reads back: a name appended twice (a line once
    unreadable) keeps its earlier day; a row without a name or an ISO date holds none."""
    text = "\n".join(
        [
            json.dumps({"note": AKC.split("/")[1], "first_seen": "2026-10-21"}),
            json.dumps({"note": AKC.split("/")[1], "first_seen": "2026-10-20"}),
            json.dumps({"note": EDGE.split("/")[1], "first_seen": "2026-10-22"}),
            json.dumps({"note": "x.md", "first_seen": "10/22"}),
            json.dumps({"note": 3, "first_seen": "2026-10-22"}),
            json.dumps(["not", "a", "row"]),
            '{"note": "cut short',
            "",
        ]
    )
    assert first_seen(text) == {
        "2026-10-20_jrp_akc.md": date(2026, 10, 20),
        "2026-10-19_jrp_edge.md": date(2026, 10, 22),
    }


def test_metrics_is_not_a_partition_so_migrate_never_touches_it(tmp_path: Path):
    vault, store = tmp_path / "vault", tmp_path / "store"
    GraphStore(store).line("akc").put([b.source()])
    _workspace(vault, AKC)
    record_opened(vault, store, date(2026, 10, 20))
    before = (store / OPENED_FILE).read_bytes()
    assert store / OPENED_FILE not in partition_files(store)
    assert prepare_store(store) == []
    assert (store / OPENED_FILE).read_bytes() == before


def test_a_store_that_cannot_take_the_file_is_one_line_not_a_stop(tmp_path: Path):
    vault, store = tmp_path / "vault", GraphStore(tmp_path / "store")
    _workspace(vault, AKC)
    store.root.mkdir()
    (store.root / "metrics").write_text("a file where the folder goes", encoding="utf-8")
    (skip,) = update_opened(store, vault, b.T0)
    assert skip.startswith("opened skip: FileExistsError: ")
    assert update_opened(GraphStore(tmp_path / "other"), vault, b.T0) == []


def _client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(fake_world()))


async def test_a_run_records_the_opened_notes_from_the_vault_dir(env: dict[str, str]):
    """Under launchd the vault dir is the stage, which holds the wrapper's copies."""
    _workspace(Path(env["JRP_VAULT_DIR"]), AKC, "Journal/private.md")
    (outcome,) = await run_pipeline(env, now=b.T0, http=_client(), pacing=False)
    store = Path(env["JRP_STORE_DIR"])
    assert _rows(store) == [{"note": "2026-10-20_jrp_akc.md", "first_seen": "2026-09-22"}]
    assert "opened skip" not in outcome.note.read_text(encoding="utf-8")


async def test_a_list_nested_too_deep_neither_stops_the_run_nor_hides_the_other(
    env: dict[str, str],
):
    vault = Path(env["JRP_VAULT_DIR"])
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "workspace.json").write_bytes(DEEP)
    _workspace(vault, EDGE, name="workspace-mobile.json")
    (outcome,) = await run_pipeline(env, now=b.T0, http=_client(), pacing=False)
    assert outcome.report.claims  # the run itself went on
    store = Path(env["JRP_STORE_DIR"])
    assert _rows(store) == [{"note": "2026-10-19_jrp_edge.md", "first_seen": "2026-09-22"}]
    assert "opened skip" not in outcome.note.read_text(encoding="utf-8")


async def test_a_failed_record_is_a_line_in_the_note_and_the_run_goes_on(env: dict[str, str]):
    _workspace(Path(env["JRP_VAULT_DIR"]), AKC)
    store = Path(env["JRP_STORE_DIR"])
    store.mkdir()
    (store / "metrics").write_text("a file where the folder goes", encoding="utf-8")
    (outcome,) = await run_pipeline(env, now=b.T0, http=_client(), pacing=False)
    assert outcome.report.claims  # the run itself went on
    assert "opened skip: FileExistsError: " in outcome.note.read_text(encoding="utf-8")
