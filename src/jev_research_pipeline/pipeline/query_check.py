"""`jrp queries check --line <slug>`: send each authored query once and show what came back.

Queries are written when a question is (questions module docstring), so the check runs at
authoring time, by whoever wrote them: every query line of every open question goes to its
adapter once, live, and the result is printed — hit count, and the newest few titles with
their dates — so a query that finds nothing, or finds the wrong field, is rewritten before
the daily run depends on it. Nothing is stored and no model is called.
"""

from collections.abc import Mapping
from typing import Final

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.questions import open_questions, question_queries

from .config import config_path, line_context, load_tracks
from .run import make_adapter

TOP_TITLES: Final = 3


async def check_queries(
    env: Mapping[str, str], slug: str, *, http: httpx2.AsyncClient, now: AwareDatetime
) -> list[str]:
    """The printed lines, one block per open question. Raises NoQuestions like a run."""
    tracks = {t.slug: t for t in load_tracks(config_path(env))}
    if slug not in tracks:
        return [f"{slug}: config.toml に無いライン"]
    ctx = line_context(tracks[slug])
    questions = open_questions(env, slug, line=ctx.line.id, now=now)
    queries = question_queries(env, slug, questions)
    out: list[str] = []
    for question in questions:
        out.append(f"## {question.title} ({question.slug})")
        authored = queries.get(question.id, ())
        if not authored:
            out.append("  クエリ未設定 — 実行時は生成経路 (Qwen + Jev query_selection)")
        for kind, text in authored:
            adapter = make_adapter(kind)
            needed = adapter.required_env
            if needed is not None and not env.get(needed):
                out.append(f"  {kind}: {text} → {needed} 未設定のため未送信")
                continue
            got = await adapter.fetch(http, ctx.line, text, now=now, env=env)
            if got.failure is not None:
                out.append(f"  {kind}: {text} → 失敗 ({got.failure.reason}: {got.failure.detail})")
                continue
            out.append(f"  {kind}: {text} → {len(got.sources)} 件")
            for s in got.sources[:TOP_TITLES]:
                when = s.published_at.isoformat() if s.published_at else "日付なし"
                out.append(f"    - {when} {s.title[:100]}")
    return out
