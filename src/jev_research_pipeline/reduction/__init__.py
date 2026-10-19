"""Reduction (decision 6): ① threshold fit, ② label → Case.
④ local decision model is deferred until a label-count threshold."""

from .cases import export_cases
from .fit import Proposal, fit_thresholds, write_proposal
from .log import DecisionLog

__all__ = [
    "DecisionLog",
    "Proposal",
    "export_cases",
    "fit_thresholds",
    "write_proposal",
]
