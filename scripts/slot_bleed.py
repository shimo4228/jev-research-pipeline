"""Slot bleed check: do batched screening answers match single-request answers?

Judge, 2026-09-23: a batched request carries several sources; if an answer tracks a
neighbour slot, the Review band is not to be trusted. This takes (source, question) pairs
the run screened in a batch, asks each alone (live Jev), and prints the route agreement and
the largest probability differences. Below 90% agreement the batch size goes down.

    uv run python scripts/slot_bleed.py <store dir> <line slug> [pairs=20]

Needs TYPESAFE_API_KEY. Live, costs ~7 Jev questions per pair; writes nothing.
The single-request state is rebuilt from the store and checked against the stored
state hash, so a pair whose state cannot be reproduced exactly is skipped, not compared.
"""

import asyncio
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import httpx2

from jev_research_pipeline.jev import JevClient, Judged, question_screening
from jev_research_pipeline.jev.core import output_of
from jev_research_pipeline.model import Claim, Judgment, Question, SourceItem
from jev_research_pipeline.pipeline.config import config_path, line_context, load_tracks
from jev_research_pipeline.store import GraphStore, input_sha256


async def main(store_dir: Path, slug: str, pairs: int) -> int:
    nodes = GraphStore(store_dir).line(slug).load()
    batched = question_screening.BATCH_ASK.sha256
    judgments = [
        n
        for n in nodes.values()
        if isinstance(n, Judgment)
        and n.function == "question_screening"
        and n.bundle_sha256 == batched
    ]
    random.Random(slug).shuffle(judgments)
    ctx = line_context({t.slug: t for t in load_tracks(config_path(os.environ))}[slug])
    jev = JevClient(httpx2.AsyncClient(timeout=30), api_key=os.environ["TYPESAFE_API_KEY"])
    rows: list[tuple[str, str, float, str]] = []
    for j in judgments:
        if len(rows) >= pairs:
            break
        source, question = nodes.get(j.subjects[0]), nodes.get(j.subjects[1])
        if not isinstance(source, SourceItem) or not isinstance(question, Question):
            continue
        # The evidence set the run judged against: the question's claims stored before today.
        evidence = [
            c.text
            for i in question.evidence
            if isinstance(c := nodes.get(i), Claim) and c.id not in set(j.subjects)
        ]
        state = question_screening.state(ctx, source, question, [])
        if input_sha256(state) != j.state_sha256:
            state = question_screening.state(ctx, source, question, evidence)
            if input_sha256(state) != j.state_sha256:
                continue  # cannot rebuild what was asked; not comparable
        single = await jev.judge(
            question_screening.ASK, j.subjects, state, now=datetime.now().astimezone()
        )
        if not isinstance(single, Judged):
            continue
        from_batch = Judged(output=output_of(question_screening.Answers, j), judgment=j)
        a = question_screening.route(from_batch, source=source)
        b = question_screening.route(single, source=source)
        diffs = {
            name: abs(float(getattr(from_batch.output, name)) - float(getattr(single.output, name)))
            for name in ("on_topic", "method_transferable", "evidence_compatible", "bridges_line")
        }
        worst = max(diffs, key=lambda k: diffs[k])
        rows.append((source.title[:60], f"{a}/{b}", diffs[worst], worst))
    agree = sum(1 for _, r, _, _ in rows if r.split("/")[0] == r.split("/")[1])
    share = f" ({agree / len(rows):.0%})" if rows else ""
    out = [
        f"pairs {len(rows)}  route agreement {agree}/{len(rows)}{share}",
        f"max |Δp| {max((d for _, _, d, _ in rows), default=0.0):.3f}",
        *(f"  {routes:16} Δp {d:.3f} ({field})  {title}" for title, routes, d, field in rows),
    ]
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(asyncio.run(main(Path(args[0]), args[1], int(args[2]) if len(args) > 2 else 20)))
