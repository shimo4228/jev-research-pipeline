"""The cost line names what Budget.cost added up for the writer at hand (plan
quality-metrics 2.1): the Jev estimate alone on a subscription writer, Jev plus the
writer's tokens on a per-token one. A price that is not set is said after it."""

import pytest

from jev_research_pipeline import note_text as t
from jev_research_pipeline.generation import parse_model
from jev_research_pipeline.note_text import LANGS, Lang
from jev_research_pipeline.pipeline.costs import Budget, cost_line

PRICED = {"JRP_JEV_USD_PER_QUESTION": "0.001"}
CLAUDE_CODE = parse_model("claude-code:claude-opus-5-5")
OPUS = parse_model("anthropic:claude-opus-5-5")
UNPRICED = parse_model("dashscope:qwen3.8-max")  # per-token, no entry in PRICES


def test_a_subscription_writer_gets_the_jev_estimate_name():
    line = cost_line(0.0193, Budget(PRICED), CLAUDE_CODE, "ja")
    assert line == "Jev 推定費用: $0.0193 (仮定単価。書き手はサブスクで 0)"


def test_a_per_token_writer_is_named_in_the_sum():
    line = cost_line(1.25, Budget(PRICED), OPUS, "ja")
    assert line == "推定費用: $1.2500 (Jev の仮定単価 + 書き手の token 代)"


def test_prices_that_are_not_set_are_said_after_the_line():
    assert cost_line(0.0, Budget({}), CLAUDE_CODE, "ja") == (
        "Jev 推定費用: $0.0000 (仮定単価。書き手はサブスクで 0) · Jev 単価未設定"
    )
    assert cost_line(0.0, Budget({}), UNPRICED, "ja") == (
        "推定費用: $0.0000 (Jev の仮定単価 + 書き手の token 代) · Jev 単価未設定 · 生成単価未設定"
    )
    assert cost_line(0.5, Budget(PRICED), UNPRICED, "ja").endswith(" · 生成単価未設定")


@pytest.mark.parametrize("lang", LANGS)
def test_every_language_branches_on_the_writer_the_same_way(lang: Lang):
    budget = Budget({})
    assert cost_line(0.0, budget, CLAUDE_CODE, lang) == (
        f"{t.COST_JEV_ONLY(lang, cost='0.0000')} · {t.JEV_PRICE_UNSET(lang)}"
    )
    assert cost_line(0.0, budget, UNPRICED, lang) == (
        f"{t.COST_WITH_WRITER(lang, cost='0.0000')} · {t.JEV_PRICE_UNSET(lang)}"
        f" · {t.GENERATION_PRICE_UNSET(lang)}"
    )
