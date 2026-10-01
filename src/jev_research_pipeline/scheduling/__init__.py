"""`jrp schedule install`: the daily run as a launchd job, written for this machine and
shown, never loaded (loading a job is the user's step; plan productize-en-zh P3).

It writes two files under ~/.config/jrp/launchd/ (each only if missing):
- launchd-jrp.sh — the package's copy of scripts/launchd-jrp.sh (tests pin the two
  equal): it stages the vault, runs `jrp doctor` and `jrp run` under a watchdog, and
  notifies what python cannot (see its header). Installed, it always starts JRP_BIN (its
  `uv run` fallback needs a checkout around it)
- local.jrp.run.plist — runs that wrapper daily at the given time, with JRP_BIN set to
  this jrp so the wrapper starts it instead of `uv run` in a checkout
and prints the two commands that load it. Linux: docs/scheduling.md (cron / systemd).
"""

import plistlib
import shlex
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Final

from jev_research_pipeline.home import JRP_HOME

LABEL: Final = "local.jrp.run"
WRAPPER: Final = "launchd-jrp.sh"


@dataclass(frozen=True)
class Scheduled:
    wrapper: Path
    plist: Path
    created: tuple[bool, bool]
    """(wrapper, plist) written now; False = it was there and was left as it was."""


def plist_bytes(
    *, wrapper: Path, jrp: Path, env_file: Path, log: Path, hour: int, minute: int
) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": ["/bin/bash", str(wrapper), "run"],
            "EnvironmentVariables": {"JRP_BIN": str(jrp), "JRP_ENV_FILE": str(env_file)},
            "StartCalendarInterval": {"Hour": hour, "Minute": minute},
            "StandardOutPath": str(log),
            "StandardErrorPath": str(log),
        }
    )


def install(
    *, jrp: Path, hour: int = 5, minute: int = 0, home: Path = JRP_HOME, log: Path | None = None
) -> Scheduled:
    out = home / "launchd"
    out.mkdir(parents=True, exist_ok=True)
    wrapper, plist = out / WRAPPER, out / f"{LABEL}.plist"
    made_wrapper = not wrapper.exists()
    if made_wrapper:
        text = (files(__package__) / WRAPPER).read_text(encoding="utf-8")
        wrapper.write_text(text, encoding="utf-8")
        wrapper.chmod(0o755)
    made_plist = not plist.exists()
    if made_plist:
        plist.write_bytes(
            plist_bytes(
                wrapper=wrapper,
                jrp=jrp,
                env_file=home / "env",
                log=log or Path.home() / "Library" / "Logs" / "jrp-run.log",
                hour=hour,
                minute=minute,
            )
        )
    return Scheduled(wrapper=wrapper, plist=plist, created=(made_wrapper, made_plist))


def install_lines(s: Scheduled) -> list[str]:
    state = ["kept   " if not c else "created" for c in s.created]
    agent = Path.home() / "Library" / "LaunchAgents" / s.plist.name
    kept = [] if all(s.created) else ["A kept file is left as it was: remove it to write it anew."]
    return [
        f"{state[0]} {s.wrapper}",
        f"{state[1]} {s.plist}",
        *kept,
        "",
        "Load it yourself (it runs daily at the time in the plist):",
        f"  cp {shlex.quote(str(s.plist))} {shlex.quote(str(agent))}",
        f"  launchctl bootstrap gui/$(id -u) {shlex.quote(str(agent))}",
    ]
