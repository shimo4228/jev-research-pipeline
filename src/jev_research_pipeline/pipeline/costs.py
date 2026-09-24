"""Cost meter and cap (decision 8: cost cap → partial report).

Generation is priced per prose model (generation.client.ModelSpec). A subscription backend
(openai-codex) is a flat plan: its tokens are counted but add nothing. A pay-per-token model
is priced from PRICES, USD per million tokens (input, output); one missing from it counts 0
and the operations section says so. Jev has no published per-question price in the packet;
it comes from env JRP_JEV_USD_PER_QUESTION (default 0 — the operations section says so).
"""

from collections.abc import Mapping
from typing import Final

from jev_research_pipeline.generation import GenerationMeter, ModelSpec

PRICES: Final = {"dashscope:qwen3.7-max": (2.5, 7.5)}
"""USD per Mtok (input, output) of the pay-per-token prose models: qwen3.7-max, Singapore,
thinking and non-thinking alike (alibabacloud.com model-pricing, as-of 2026-09-23)."""
JEV_PRICE_ENV: Final = "JRP_JEV_USD_PER_QUESTION"
COST_CAP_ENV: Final = "JRP_COST_CAP_USD"


def _float(env: Mapping[str, str], name: str) -> float | None:
    raw = env.get(name)
    return float(raw) if raw else None


def generation_price(spec: ModelSpec) -> tuple[float, float] | None:
    """USD per Mtok (input, output); None = a per-token model with no price on record."""
    if spec.subscription:
        return (0.0, 0.0)
    return PRICES.get(str(spec))


class Budget:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.cap = _float(env, COST_CAP_ENV)
        self.jev_price = _float(env, JEV_PRICE_ENV) or 0.0
        self.jev_price_known = env.get(JEV_PRICE_ENV) is not None

    def cost(self, *, jev_questions: int, meters: Mapping[ModelSpec, GenerationMeter]) -> float:
        total = jev_questions * self.jev_price
        for spec, m in meters.items():
            p_in, p_out = generation_price(spec) or (0.0, 0.0)
            total += (m.input_tokens * p_in + m.output_tokens * p_out) / 1_000_000
        return total

    def exceeded(self, *, jev_questions: int, meters: Mapping[ModelSpec, GenerationMeter]) -> bool:
        return (
            self.cap is not None
            and self.cost(jev_questions=jev_questions, meters=meters) > self.cap
        )
