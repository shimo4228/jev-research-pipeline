"""Cost meter and cap (decision 8: cost cap → partial report).

Qwen prices: packet decision 10 (as-of 2026-09-22), USD per million tokens (input,
output). Jev has no published per-question price in the packet; it comes from env
JRP_JEV_USD_PER_QUESTION (default 0 — the operations section says so).
"""

from collections.abc import Mapping
from typing import Final

from jev_research_pipeline.qwen import FLASH, MAX, GenerationMeter

PRICES: Final = {FLASH: (0.15, 0.61), MAX: (2.0, 6.0)}
"""USD per Mtok (input, output). deepseek-v4.1-flash: Singapore idle 1.094 / 4.375 CNY at
~7.2 CNY/USD (help.aliyun.com, as-of 2026-09-23; busy hours cost twice that)."""
JEV_PRICE_ENV: Final = "JRP_JEV_USD_PER_QUESTION"
COST_CAP_ENV: Final = "JRP_COST_CAP_USD"


def _float(env: Mapping[str, str], name: str) -> float | None:
    raw = env.get(name)
    return float(raw) if raw else None


class Budget:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.cap = _float(env, COST_CAP_ENV)
        self.jev_price = _float(env, JEV_PRICE_ENV) or 0.0
        self.jev_price_known = env.get(JEV_PRICE_ENV) is not None

    def cost(self, *, jev_questions: int, meters: Mapping[str, GenerationMeter]) -> float:
        total = jev_questions * self.jev_price
        for model, m in meters.items():
            p_in, p_out = PRICES[model]
            total += (m.input_tokens * p_in + m.output_tokens * p_out) / 1_000_000
        return total

    def exceeded(self, *, jev_questions: int, meters: Mapping[str, GenerationMeter]) -> bool:
        return (
            self.cap is not None
            and self.cost(jev_questions=jev_questions, meters=meters) > self.cap
        )
