"""Where eval sets live: `<JRP_STORE_DIR>/evals/<kind>/<name>/`, beside prose_bench/. It is not
a partition (store.migrate reads lines/ and pipeline.jsonld only), and it holds third-party
text (abstracts, excerpts), so it stays in the private store and never in the repo. With
JRP_EVAL_DIR set, the evals live there instead (a scratch run points it at a scratch folder)."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from jev_research_pipeline.pipeline.runner import store_dir

EVALS_DIR: Final = "evals"
EVAL_DIR_ENV: Final = "JRP_EVAL_DIR"
NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
"""A kind or set name: one path segment, never `..` or a separator."""


def eval_root(env: Mapping[str, str]) -> Path:
    raw = env.get(EVAL_DIR_ENV)
    return Path(raw) if raw else store_dir(env) / EVALS_DIR


def bench_dir(env: Mapping[str, str], kind: str, name: str) -> Path:
    """One eval set: `kind` is the eval (`gate`, `intake`), `name` the set. Raise ValueError
    on a name that is not one plain path segment."""
    for part in (kind, name):
        if not NAME.match(part) or ".." in part:
            raise ValueError(f"not an eval set name: {part!r}")
    return eval_root(env) / kind / name
