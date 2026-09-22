"""Derived claim index: SQLite FTS5 + bm25 over claim text, one file per partition.

Derived, never a source of truth: rebuild() recreates it from the partition's Claims
alone, so deleting the file loses nothing. It is a candidate pre-pass (novelty pairs,
retrieval) — recall over precision, so multi-term queries are OR-ed and bm25-ranked.

Tokenization happens in Python before FTS5 sees the text (index_tokens), for both the
indexed text and the query, so the two always agree:
- CJK runs (kana + kanji) → overlapping character bigrams + the run's last character.
  FTS5's trigram tokenizer cannot match 2-character words like 検索 (measured
  2026-09-22); bigrams can. A one-character CJK query becomes a prefix match: every
  character of a run starts some bigram except the last, which the trailing unigram
  covers — so 社 in X社は and う in 飼う are both reachable.
- Other word runs → lowercased whole words.
FTS5's default unicode61 tokenizer then only splits the space-joined tokens.
"""

import contextlib
import os
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from typing import Final

from jev_research_pipeline.model import Claim

from .graph import Partition

# Hiragana, Katakana (incl. the long-vowel mark), CJK Ext A, CJK Unified, CJK Compatibility, halfwidth kana.
# CJK punctuation (U+3000-303F) is deliberately outside: it is dropped like other punctuation.
_CJK: Final = r"\u3041-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f"
_TOKEN_RE: Final = re.compile(rf"([{_CJK}]+)|([^\W_{_CJK}]+)")
_CJK_CHAR_RE: Final = re.compile(rf"[{_CJK}]")

_SCHEMA: Final = "CREATE VIRTUAL TABLE claims USING fts5(claim_id UNINDEXED, tokens)"
_SEARCH: Final = (
    "SELECT claim_id FROM claims WHERE claims MATCH ? ORDER BY bm25(claims), claim_id LIMIT ?"
)


def index_tokens(text: str) -> list[str]:
    """NFKC first, so full-width Latin and half-width kana index like their canonical forms."""
    tokens: list[str] = []
    for cjk, word in _TOKEN_RE.findall(unicodedata.normalize("NFKC", text)):
        if len(cjk) == 1:
            tokens.append(cjk)
        elif cjk:
            tokens.extend(cjk[i : i + 2] for i in range(len(cjk) - 1))
            tokens.append(cjk[-1])
        else:
            tokens.append(word.casefold())
    return tokens


def _match_expression(query: str) -> str | None:
    """OR of quoted tokens. Tokens are word characters only, so quoting cannot be broken
    and FTS5 operators in untrusted text (NEAR, *, AND) are never parsed as syntax."""
    tokens = index_tokens(query)
    if not tokens:
        return None
    terms = [
        f'"{t}"*' if len(t) == 1 and _CJK_CHAR_RE.match(t) else f'"{t}"'
        for t in dict.fromkeys(tokens)
    ]
    return " OR ".join(terms)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    """mode=ro: a deleted index raises instead of being silently recreated empty (which
    would also make open() believe the index exists)."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


class ClaimIndex:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def open(cls, path: Path) -> "ClaimIndex":
        if not path.exists():
            raise FileNotFoundError(f"claim index missing (rebuild it from the store): {path}")
        return cls(path)

    @classmethod
    def rebuild(cls, path: Path, partition: Partition) -> "ClaimIndex":
        """Build into a temp file, then os.replace: readers never see a half-built index."""
        claims = [n for n in partition.load().values() if isinstance(n, Claim)]
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        os.close(fd)
        try:
            with contextlib.closing(sqlite3.connect(tmp)) as con, con:
                con.execute(_SCHEMA)
                con.executemany(
                    "INSERT INTO claims (claim_id, tokens) VALUES (?, ?)",
                    [
                        (c.id, " ".join(index_tokens(c.text)))
                        for c in sorted(claims, key=lambda c: c.id)
                    ],
                )
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return cls(path)

    def search(self, query: str, *, limit: int) -> list[str]:
        """Claim @ids, best bm25 match first; ties broken by @id for determinism."""
        expr = _match_expression(query)
        if expr is None:
            return []
        with contextlib.closing(_connect_read_only(self.path)) as con:
            rows: list[tuple[str]] = con.execute(_SEARCH, (expr, limit)).fetchall()
        return [claim_id for (claim_id,) in rows]

    def claim_ids(self) -> set[str]:
        with contextlib.closing(_connect_read_only(self.path)) as con:
            rows: list[tuple[str]] = con.execute("SELECT claim_id FROM claims").fetchall()
        return {claim_id for (claim_id,) in rows}
