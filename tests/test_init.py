"""`jrp init` and `jrp try` (init.py): a first setup that runs, and one run in a scratch
folder that touches nothing real."""

import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

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


def test_the_packaged_question_skill_is_the_repos_skill():
    """`jrp questions new` hands Claude Code the package's copy; it must stay the skill."""
    repo = Path(__file__).parents[1]
    packaged = repo / "src" / "jev_research_pipeline" / "skills" / "jrp-question.md"
    skill = repo / ".claude" / "skills" / "jrp-question" / "SKILL.md"
    assert packaged.read_text(encoding="utf-8") == skill.read_text(encoding="utf-8")


def test_the_question_session_carries_the_skill_and_the_file(tmp_path: Path):
    from jev_research_pipeline.init import question_session

    argv = question_session(Path("/bin/claude"), "memo", tmp_path / "memo.md")
    assert argv[:2] == ["/bin/claude", "--append-system-prompt"]
    assert "# Questions for a jrp line" in argv[2]
    assert "`memo`" in argv[3] and str(tmp_path / "memo.md") in argv[3]
    assert "does not exist yet" in argv[3]


def test_the_question_session_runs_without_the_claude_api_key(monkeypatch: pytest.MonkeyPatch):
    """An ANTHROPIC_API_KEY sourced from the env file would move the interactive Claude Code
    session off the author's subscription onto API billing: the session runs without it."""
    from jev_research_pipeline import cli
    from jev_research_pipeline.pipeline.config import TrackSpec

    seen: dict[str, object] = {}

    def run(
        argv: list[str], *, check: bool, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        seen["env"] = env
        return subprocess.CompletedProcess(argv, 0)

    def tracks(_env: object) -> list[TrackSpec]:
        return [TrackSpec(slug="memo", name="memo", repo=None, daily=False)]

    def binary(_env: object) -> Path:
        return Path("/bin/claude")

    monkeypatch.setattr(cli, "env_tracks", tracks)
    monkeypatch.setattr(cli, "claude_bin", binary)
    monkeypatch.setattr(cli.subprocess, "run", run)
    env = {
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "TYPESAFE_API_KEY": "t",
        "HOME": "/h",
        "PATH": "/bin",
    }
    assert cli._questions_new(env, "memo") == 0  # pyright: ignore[reportPrivateUsage]
    passed = seen["env"]
    assert isinstance(passed, dict)
    assert "ANTHROPIC_API_KEY" not in passed
    assert passed["TYPESAFE_API_KEY"] == "t" and passed["HOME"] == "/h"  # the skill's steps keep it
