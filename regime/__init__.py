"""
regime/ — 市场状态分类与边界推导

导出 MarketRegime、DerivedBoundaries、classify()、compute_derived_boundaries()。
"""

from .boundary import (
    DerivedBoundaries,
    MarketRegime,
    RegimeClass,
    classify,
    compute_derived_boundaries,
)

__all__ = [
    "MarketRegime",
    "RegimeClass",
    "DerivedBoundaries",
    "classify",
    "compute_derived_boundaries",
]
