"""`jrp init` and `jrp try` (init.py): a first setup that runs, and one run in a scratch
folder that touches nothing real."""

import stat
from datetime import UTC, datetime
from pathlib import Path

from jev_research_pipeline.home import DATA_HOME
from jev_research_pipeline.init import EXAMPLE_LINE, init, try_line
from jev_research_pipeline.pipeline.config import line_context, load_tracks, rotation_config
from jev_research_pipeline.questions import open_questions, question_queries
from jev_research_pipeline.store import GraphStore

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_world
from .test_e2e import env as env


def test_init_writes_a_setup_that_loads(tmp_path: Path):
    written = init(home=tmp_path, lang="zh", today="2026-10-01")
    assert [w.created for w in written] == [True, True, True]
    env_file = tmp_path / "env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600  # it will hold keys
    text = env_file.read_text(encoding="utf-8")
    assert "JRP_NOTE_LANG=zh" in text
    # doctor and the launchd wrapper both ask for it by name
    assert f'JRP_STORE_DIR="{DATA_HOME / "store"}"' in text

    (track,) = load_tracks(tmp_path / "config.toml")
    assert track.slug == EXAMPLE_LINE and track.repo is None
    assert rotation_config([track], per_tick=3).order == (EXAMPLE_LINE,)
    env = {"JRP_QUESTIONS_DIR": str(tmp_path / "questions")}
    ctx = line_context(track)
    (question,) = open_questions(
        env, EXAMPLE_LINE, line=ctx.line.id, now=datetime(2026, 10, 1, tzinfo=UTC)
    )
    assert "benchmark" in question.brief
    queries = question_queries(env, EXAMPLE_LINE, [question])[question.id]
    assert {kind for kind, _ in queries} == {"arxiv", "github", "hf_papers"}


def test_init_never_touches_a_file_that_exists(tmp_path: Path):
    (tmp_path / "config.toml").write_text("# mine\n", encoding="utf-8")
    first = init(home=tmp_path)
    assert [w.created for w in first] == [True, False, True]
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == "# mine\n"
    assert [w.created for w in init(home=tmp_path)] == [False, False, False]


async def test_try_runs_one_line_into_a_scratch_folder(
    cassette: ClientFactory,
    env: dict[str, str],
    tmp_path: Path,
):
    """The note lands under <root>/try/<time>/vault; the env's own store and vault get
    nothing, and the rotation does not move."""
    root = tmp_path / "data"
    tried = await try_line(env, "akc", http=cassette(fake_world()), now=b.T0, root=root)
    assert tried is not None
    (note,) = tried.notes
    assert note.is_relative_to(root / "try") and note.exists()
    assert tried.lines[-1] == f"note: {note}"
    assert not list(Path(env["JRP_VAULT_DIR"]).rglob("*.md"))
    assert not GraphStore(Path(env["JRP_STORE_DIR"])).root.exists()
    assert await try_line(env, "nope", http=cassette(fake_world()), now=b.T0, root=root) is None
