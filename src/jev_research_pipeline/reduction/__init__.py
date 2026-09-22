"""Reduction (decision 6): ① threshold fit, ② label → Case, ③ rule candidates.
④ local decision model is deferred until a label-count threshold."""

from .cases import export_cases
from .fit import Proposal, fit_thresholds, write_proposal
from .log import DecisionLog
from .rules import RuleConfig, rule_candidates

__all__ = [
    "DecisionLog",
    "Proposal",
    "RuleConfig",
    "export_cases",
    "fit_thresholds",
    "rule_candidates",
    "write_proposal",
]
