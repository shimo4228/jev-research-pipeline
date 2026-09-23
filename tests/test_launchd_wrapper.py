"""scripts/launchd-jrp.sh stages the vault for `jrp run`: python must never open the
iCloud vault under launchd (TCC), so bash copies notes in and the run's notes back out."""

import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "launchd-jrp.sh"

# A stand-in for uv: asserts it was pointed at the stage, harvests (reads) a staged note,
# rewrites one note and writes a new one — what `jrp run` does to the vault dir.
FAKE_UV = """#!/usr/bin/env bash
set -euo pipefail
notes="$JRP_VAULT_DIR/daily-research"
[[ "$JRP_VAULT_DIR" == "$EXPECT_STAGE" ]] || { echo "vault not staged: $JRP_VAULT_DIR"; exit 9; }
grep -q "[x]" "$notes/2026-09-23_jrp_akc.md"
echo "rewritten" > "$notes/2026-09-24_jrp_akc.md"
echo "new" > "$notes/2026-09-24_jrp_aap.md"
echo "args: $*"
"""


def _setup(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    vault = tmp_path / "vault" / "daily-research"
    vault.mkdir(parents=True)
    (vault / "2026-09-23_jrp_akc.md").write_text("- [x] ticked\n")
    (vault / "2026-09-24_jrp_akc.md").write_text("old\n")
    (vault / "2026-09-23_edge_other.md").write_text("not a jrp note\n")
    old = time.time() - 3600
    os.utime(vault / "2026-09-23_jrp_akc.md", (old, old))
    uv = tmp_path / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    store = tmp_path / "store"
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "JRP_ENV_FILE": str(tmp_path / "no-env"),
        "JRP_UV": str(uv),
        "JRP_VAULT_DIR": str(tmp_path / "vault"),
        "JRP_STORE_DIR": str(store),
        "EXPECT_STAGE": str(store / "vault-stage"),
    }
    return env, vault, store / "vault-stage" / "daily-research"


def test_run_stages_the_vault_and_copies_back_only_what_it_wrote(tmp_path: Path):
    env, vault, stage = _setup(tmp_path)
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    assert "--frozen jrp run" in out.stdout
    assert (vault / "2026-09-24_jrp_akc.md").read_text() == "rewritten\n"
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"
    assert (vault / "2026-09-23_jrp_akc.md").read_text() == "- [x] ticked\n"  # untouched
    assert (vault / "2026-09-23_edge_other.md").exists()  # nothing deleted in the vault
    assert not (stage / "2026-09-23_edge_other.md").exists()  # only jrp notes are staged
    assert "vault ← 2026-09-24_jrp_aap.md" in out.stdout
    assert "2026-09-23_jrp_akc.md" not in out.stdout  # read, not written: not copied back


def test_other_commands_do_not_stage(tmp_path: Path):
    env, _, stage = _setup(tmp_path)
    out = subprocess.run(
        ["bash", str(SCRIPT), "drift"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 9  # the fake saw the real vault dir: drift is passed through
    assert not stage.exists()
