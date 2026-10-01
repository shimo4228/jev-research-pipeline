"""Where jrp keeps a user's files when the environment names no other place (`jrp init`
writes them here). The author's machine names every path in ~/.config/jrp/env, so these
defaults apply to a fresh install only.

    ~/.config/jrp/env          the run's environment (paths, keys), sourced by the wrapper
    ~/.config/jrp/config.toml  the lines (JRP_DAILY_RESEARCH_CONFIG)
    ~/.config/jrp/questions/   one question file per line (JRP_QUESTIONS_DIR)
    ~/.local/share/jrp/store/  the pipeline's state (JRP_STORE_DIR)
"""

from pathlib import Path
from typing import Final

JRP_HOME: Final = Path.home() / ".config" / "jrp"
DATA_HOME: Final = Path.home() / ".local" / "share" / "jrp"
