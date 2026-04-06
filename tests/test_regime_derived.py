"""
tests/test_regime_derived.py — DerivedBoundaries 参数计算测试 (Part 2)

测试覆盖:
- sigma_multiplier 随 iv_consensus 和 iv_divergence 变化
- dte_gravity 和 default_dte 由 contango 决定
- cache_ttl 由 vol_of_vol 决定
- confidence 标签由 iv_divergence 决定
- default_strikes 的硬边界 [8, 30]

三级分类正确性 + §5.6 数值示例见 test_regime.py
"""

import pytest

from regime.boundary import (
    DerivedBoundaries,
    MarketRegime,
    classify,
    compute_derived_boundaries,
)

# ── Constants ──

SPOT = 218.50
STEP = 2.50


# ── Helpers ──

def make_regime(
    iv30d: float = 0.22,
    contango: float = 1.0,
    vrp: float = 0.03,
    iv_rank: float = 48.0,
    iv_pctl: float = 52.0,
    vol_of_vol: float = 0.05,
) -> MarketRegime:
    """构造 MarketRegime，提供合理默认值（NORMAL 场景）。"""
    return MarketRegime(
        iv30d=iv30d,
        contango=contango,
        vrp=vrp,
        iv_rank=iv_rank,
        iv_pctl=iv_pctl,
        vol_of_vol=vol_of_vol,
    )


# ── sigma_multiplier Tests ──


class TestSigmaMultiplier:
    """sigma_multiplier 随 iv_consensus 和 iv_divergence 变化。"""

    def test_high_consensus_gets_2_5(self):
        """iv_consensus > 70 → sigma_multiplier = 2.5。"""
        r = make_regime(iv_rank=80.0, iv_pctl=85.0)
        # iv_consensus = 0.4×80 + 0.6×85 = 83 > 70
        b = compute_derived_boundaries(r, SPOT, STEP)
        # No divergence: 83-80=3 < 30, so no ×1.1
        assert b.sigma_multiplier == pytest.approx(2.5)

    def test_low_consensus_gets_2_2(self):
        """iv_consensus < 30 → sigma_multiplier = 2.2。"""
        r = make_regime(iv30d=0.12, iv_rank=18.0, iv_pctl=22.0)
        # iv_consensus = 0.4×18 + 0.6×22 = 20.4 < 30
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.sigma_multiplier == pytest.approx(2.2)

    def test_normal_consensus_gets_2_0(self):
        """30 ≤ iv_consensus ≤ 70 → sigma_multiplier = 2.0。"""
        r = make_regime(iv_rank=48.0, iv_pctl=52.0)
        # iv_consensus = 50, no divergence
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.sigma_multiplier == pytest.approx(2.0)

    def test_high_divergence_applies_1_1_multiplier(self):
        """iv_divergence > 30 → sigma_multiplier × 1.1。"""
        r = make_regime(iv_rank=23.0, iv_pctl=78.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.sigma_multiplier == pytest.approx(2.0 * 1.1, rel=0.01)

    def test_low_divergence_no_multiplier(self):
        """iv_divergence ≤ 30 → 无额外 ×1.1。"""
        r = make_regime(iv_rank=48.0, iv_pctl=52.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.sigma_multiplier == pytest.approx(2.0)  # 不乘 1.1


# ── DTE Gravity Tests ──


class TestDTEGravity:
    """dte_gravity 由 contango 方向决定。"""

    def test_backwardation_near(self):
        """contango < -2 → dte_gravity='near', default_dte=30。"""
        r = make_regime(contango=-3.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.dte_gravity == "near"
        assert b.default_dte == 30

    def test_contango_far(self):
        """contango > +2 → dte_gravity='far', default_dte=75。"""
        r = make_regime(contango=3.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.dte_gravity == "far"
        assert b.default_dte == 75

    def test_flat_balanced(self):
        """-2 ≤ contango ≤ +2 → dte_gravity='balanced', default_dte=60。"""
        r = make_regime(contango=1.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.dte_gravity == "balanced"
        assert b.default_dte == 60


# ── Cache TTL Tests ──


class TestCacheTTL:
    """cache_ttl 由 vol_of_vol 决定。"""

    def test_high_vol_of_vol_short_ttl(self):
        """vol_of_vol > 0.08 → cache_ttl = 120s（2 分钟）。"""
        r = make_regime(vol_of_vol=0.10)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.cache_ttl == 120

    def test_low_vol_of_vol_long_ttl(self):
        """vol_of_vol < 0.04 → cache_ttl = 600s（10 分钟）。"""
        r = make_regime(vol_of_vol=0.02)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.cache_ttl == 600

    def test_normal_vol_of_vol_standard_ttl(self):
        """0.04 ≤ vol_of_vol ≤ 0.08 → cache_ttl = 300s（5 分钟）。"""
        r = make_regime(vol_of_vol=0.05)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.cache_ttl == 300


# ── Confidence Tests ──


class TestConfidence:
    """confidence 标签由 iv_divergence 决定。"""

    def test_high_divergence_low_confidence(self):
        """iv_divergence > 30 → confidence='LOW'。"""
        r = make_regime(iv_rank=23.0, iv_pctl=78.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.confidence == "LOW"

    def test_low_divergence_high_confidence(self):
        """iv_divergence ≤ 30 → confidence='HIGH'。"""
        r = make_regime(iv_rank=48.0, iv_pctl=52.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.confidence == "HIGH"

    def test_boundary_divergence_30(self):
        """iv_divergence = 30 (边界) → confidence='HIGH'（不 > 30）。"""
        r = make_regime(iv_rank=50.0, iv_pctl=80.0)
        # iv_divergence = |50 - 80| = 30，不 > 30
        assert r.iv_divergence == pytest.approx(30.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.confidence == "HIGH"


# ── DerivedBoundaries Bounds Tests ──


class TestStrikeBounds:
    """default_strikes 的硬边界 [8, 30]。"""

    def test_minimum_bound(self):
        """极端低波下 default_strikes 不低于 8。"""
        r = make_regime(iv30d=0.01, iv_rank=5.0, iv_pctl=5.0)
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.default_strikes >= 8

    def test_maximum_bound(self):
        """极端高波下 default_strikes 不超过 30。"""
        r = make_regime(
            iv30d=1.0, contango=-5.0, iv_rank=99.0, iv_pctl=99.0
        )
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.default_strikes <= 30

    def test_returns_derived_boundaries_instance(self):
        """compute_derived_boundaries 应返回 DerivedBoundaries 实例。"""
        r = make_regime()
        b = compute_derived_boundaries(r, SPOT, STEP)
        assert isinstance(b, DerivedBoundaries)
