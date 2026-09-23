"""Qwen site 1b: question candidates for a line (the FLASH model, qwen.client).

Seeds are gathered by code — the line's ResearchLine description and the "Review-when"
lines of its ADRs, i.e. the conditions the author already wrote down for revisiting a
decision. Qwen phrases candidate questions from them; Jev (question_seeding) scores them;
the note proposes them with a checkbox and the author adopts. One candidate per round is
asked for from a changed vantage point, because a proposal round that only rephrases the
line's own vocabulary cannot open anything new (packet "Question-centric redesign").

The FLASH output mode over a Pydantic model (client.flash_output), same as the query site; a failed or empty generation
yields no proposals rather than a made-up one.
"""

import re
from collections.abc import Sequence
from typing import Final

from pydantic import AwareDatetime, BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import Question, sha256_hex
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.query_text import clean_query
from jev_research_pipeline.questions import slugify

from .client import GenerationMeter, flash_output

PROPOSALS: Final = 5
"""Per round. The author reads them in the note; more than a handful is a wall."""
OUTPUT_RETRIES: Final = 2


class Candidate(BaseModel):
    """One proposed research question."""

    title: str = Field(description="The question itself, in Japanese, as one sentence.")
    brief: str = Field(description="What an answer would settle, in one sentence.")


class CandidateList(BaseModel):
    questions: list[Candidate] = Field(min_length=1)


class ProposalResult(Value):
    questions: tuple[Question, ...]
    failure: str | None


def instructions(n: int) -> str:
    return (
        f"あなたは研究ラインの「問い」を提案する。JSON で `questions` という 1 つの field を返す: "
        f"{n} 件の候補。各候補は `title` に問いそのものを日本語 1 文で、`brief` に答えが何を決めるかを "
        "1 文で書く。うち 1 件は、与えられた語彙の外側から見た視点で立てる。"
        "答えが証拠で動く問いにする。前置きや解説は書かない。"
    )


def user_prompt(ctx: LineContext, seeds: list[str], existing: Sequence[Question] = ()) -> str:
    vocab = "\n".join(f"- {term}" for term in ctx.vocabulary)
    lines = [f"研究ライン: {ctx.line.name}", f"語彙:\n{vocab}"]
    if existing:
        # Without them a proposal redefined a term the author's file already defines
        # (scratch run 6: 三軸反転 given other axes than the question file's).
        held = "\n".join(f"- {q.title}: {q.brief}" for q in existing)
        lines.append(f"すでにある問い (重複させず、用語の定義はこれに従う):\n{held}")
    if seeds:
        joined = "\n".join(f"- {s}" for s in seeds)
        lines.append(f"著者が書き残した見直し条件:\n{joined}")
    return "\n\n".join(lines)


_FOREIGN_SCRIPT: Final = re.compile(
    r"[\u0400-\u04ff\u0590-\u06ff\u0e00-\u0e7f\u1100-\u11ff\uac00-\ud7af]"
)
"""Cyrillic, Hebrew/Arabic, Thai, Hangul: a Japanese proposal with any of these is a
generation slip (scratch run 6: "オン톨ロジー"), never meant."""


def _question(ctx: LineContext, candidate: Candidate, now: AwareDatetime) -> Question | None:
    title = " ".join(candidate.title.split())
    if clean_query(title) is None:
        return None  # the same contamination guard as the query site
    if _FOREIGN_SCRIPT.search(title + candidate.brief):
        return None
    return Question.new(
        line=ctx.line.id,
        # A proposal's slug is made here, not by the author: a stray digit ("3" from
        # 三軸…) is not a slug, so short ones take the hash form.
        slug=slug if len(slug := slugify(title)) >= 4 else f"q-{sha256_hex(title)[:8]}",
        version=1,
        title=title,
        brief=" ".join(candidate.brief.split()),
        opened_at=now,
    )


PROPOSAL_TIMEOUT_S: Final = 120.0
"""Per request, over the shared client's 30 s: the first pilot's proposal call died with a
bare ModelAPIError on every line (2026-09-23), the way the prose call did at 30 s."""


async def propose_questions(
    model: OpenAIChatModel,
    ctx: LineContext,
    seeds: list[str],
    *,
    n: int = PROPOSALS,
    meter: GenerationMeter,
    now: AwareDatetime,
    existing: Sequence[Question] = (),
) -> ProposalResult:
    agent = Agent(
        model,
        output_type=flash_output(CandidateList),
        instructions=instructions(n),
        retries={"output": OUTPUT_RETRIES},
        model_settings=ModelSettings(timeout=PROPOSAL_TIMEOUT_S),
    )
    usage = RunUsage()
    try:
        result = await agent.run(user_prompt(ctx, seeds, existing), usage=usage)
    except AgentRunError as e:
        if isinstance(e, UnexpectedModelBehavior):
            meter.output_violations += 1
        detail = " ".join(str(e).split())[:120]
        return ProposalResult(questions=(), failure=f"{type(e).__name__}: {detail}")
    finally:
        meter.add(usage)
    made = [q for c in result.output.questions[:n] if (q := _question(ctx, c, now)) is not None]
    unique = list({q.slug: q for q in made}.values())
    return ProposalResult(questions=tuple(unique), failure=None if unique else "empty")
