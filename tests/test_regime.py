"""
tests/test_regime.py — 市场状态分类正确性测试 (Part 1)

测试覆盖:
- iv_consensus 和 iv_divergence 属性计算
- classify(): 三级市场状态决策树
- 设计文档 §5.6 的四组数值示例

sigma_multiplier / DTE gravity / cache_ttl / confidence / strike bounds
测试见 test_regime_derived.py
"""

import pytest

from regime.boundary import (
    DerivedBoundaries,
    MarketRegime,
    RegimeClass,
    classify,
    compute_derived_boundaries,
)


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


# ── iv_consensus / iv_divergence Tests ──


class TestIVConsensusAndDivergence:
    """iv_consensus 与 iv_divergence 属性计算。"""

    def test_consensus_formula(self):
        """iv_consensus = 0.4 × IVR + 0.6 × IVP。"""
        r = make_regime(iv_rank=48.0, iv_pctl=52.0)
        expected = 0.4 * 48.0 + 0.6 * 52.0
        assert r.iv_consensus == pytest.approx(expected)

    def test_consensus_low_scenario(self):
        """低波环境: IVR=18, IVP=22 → consensus = 0.4×18 + 0.6×22 = 20.4。"""
        r = make_regime(iv_rank=18.0, iv_pctl=22.0)
        assert r.iv_consensus == pytest.approx(0.4 * 18.0 + 0.6 * 22.0)

    def test_consensus_stress_scenario(self):
        """压力环境: IVR=90, IVP=82 → consensus = 0.4×90 + 0.6×82 = 85.2。"""
        r = make_regime(iv_rank=90.0, iv_pctl=82.0)
        assert r.iv_consensus == pytest.approx(0.4 * 90.0 + 0.6 * 82.0)

    def test_divergence_low(self):
        """低分歧: |48-52| = 4。"""
        r = make_regime(iv_rank=48.0, iv_pctl=52.0)
        assert r.iv_divergence == pytest.approx(4.0)

    def test_divergence_high(self):
        """高分歧: |23-78| = 55（财报后 IV crush 典型场景）。"""
        r = make_regime(iv_rank=23.0, iv_pctl=78.0)
        assert r.iv_divergence == pytest.approx(55.0)

    def test_divergence_zero(self):
        """IVR = IVP 时分歧为 0。"""
        r = make_regime(iv_rank=50.0, iv_pctl=50.0)
        assert r.iv_divergence == pytest.approx(0.0)


# ── classify() Tests ──


class TestClassify:
    """classify(): 三级市场状态决策树。"""

    def test_backwardation_is_stress(self):
        """contango < -2 → STRESS（最强信号，优先级最高）。"""
        r = make_regime(contango=-3.2, iv30d=0.38, iv_rank=90.0, iv_pctl=82.0)
        assert classify(r) == RegimeClass.STRESS

    def test_backwardation_overrides_other_signals(self):
        """即使 IV 不高，backwardation 仍应触发 STRESS。"""
        r = make_regime(contango=-5.0, iv30d=0.15, iv_rank=20.0, iv_pctl=25.0)
        assert classify(r) == RegimeClass.STRESS

    def test_high_iv_high_consensus_is_stress(self):
        """iv30d > 0.25 AND iv_consensus > 70 → STRESS。"""
        r = make_regime(
            iv30d=0.30, contango=1.0, iv_rank=80.0, iv_pctl=85.0
        )
        # iv_consensus = 0.4×80 + 0.6×85 = 83 > 70
        assert classify(r) == RegimeClass.STRESS

    def test_high_iv_low_consensus_is_normal(self):
        """iv30d > 0.25 但 iv_consensus ≤ 70 → NORMAL（双重门槛）。"""
        r = make_regime(
            iv30d=0.30, contango=1.0, iv_rank=50.0, iv_pctl=55.0
        )
        # iv_consensus = 0.4×50 + 0.6×55 = 53 < 70
        assert classify(r) == RegimeClass.NORMAL

    def test_low_vol_classification(self):
        """iv_consensus < 30 AND iv30d < 0.15 → LOW_VOL。"""
        r = make_regime(iv30d=0.12, contango=3.5, iv_rank=18.0, iv_pctl=22.0)
        # iv_consensus = 0.4×18 + 0.6×22 = 20.4 < 30
        assert classify(r) == RegimeClass.LOW_VOL

    def test_low_consensus_high_iv_is_normal(self):
        """iv_consensus < 30 但 iv30d ≥ 0.15 → NORMAL。"""
        r = make_regime(iv30d=0.20, contango=1.0, iv_rank=15.0, iv_pctl=20.0)
        # iv_consensus = 0.4×15 + 0.6×20 = 18 < 30, 但 iv30d=0.20 ≥ 0.15
        assert classify(r) == RegimeClass.NORMAL

    def test_normal_classification(self):
        """中间状态 → NORMAL。"""
        r = make_regime(iv30d=0.22, contango=1.0, iv_rank=48.0, iv_pctl=52.0)
        assert classify(r) == RegimeClass.NORMAL


# ── §5.6 数值示例 Tests ──

# 示例中使用 AAPL: spot=$218.50, est_strike_step=$2.50

SPOT = 218.50
STEP = 2.50


class TestSection56Examples:
    """设计文档 §5.6 的四组数值示例验证。"""

    def test_low_vol_example(self):
        """LOW_VOL: iv30d=12%, IVR=18, IVP=22, contango=+3.5
        → regime=LOW_VOL, default_dte=75, default_strikes≈10。
        """
        r = make_regime(iv30d=0.12, contango=3.5, iv_rank=18.0, iv_pctl=22.0)
        assert classify(r) == RegimeClass.LOW_VOL

        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.default_dte == 75
        assert b.dte_gravity == "far"          # contango > 2
        assert b.default_strikes == pytest.approx(10, abs=2)

    def test_normal_example(self):
        """NORMAL: iv30d=22%, IVR=48, IVP=52, contango=+1.0
        → regime=NORMAL, default_dte=60, default_strikes≈14。
        """
        r = make_regime(iv30d=0.22, contango=1.0, iv_rank=48.0, iv_pctl=52.0)
        assert classify(r) == RegimeClass.NORMAL

        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.default_dte == 60
        assert b.dte_gravity == "balanced"
        assert b.default_strikes == pytest.approx(14, abs=2)

    def test_normal_high_divergence_example(self):
        """NORMAL 高分歧: iv30d=22%, IVR=23, IVP=78, contango=+1.0
        → regime=NORMAL, default_strikes≈16 (sigma_multiplier ×1.1)。
        """
        r = make_regime(iv30d=0.22, contango=1.0, iv_rank=23.0, iv_pctl=78.0)
        # iv_consensus = 0.4×23 + 0.6×78 = 9.2 + 46.8 = 56 → NORMAL
        assert classify(r) == RegimeClass.NORMAL
        # iv_divergence = |23-78| = 55 > 30
        assert r.iv_divergence > 30

        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.default_dte == 60
        assert b.sigma_multiplier == pytest.approx(2.0 * 1.1, rel=0.01)
        assert b.confidence == "LOW"
        assert b.default_strikes == pytest.approx(16, abs=2)

    def test_stress_example(self):
        """STRESS: iv30d=38%, IVR=90, IVP=82, contango=-3.2
        → regime=STRESS, default_dte=30, default_strikes≈24。
        """
        r = make_regime(iv30d=0.38, contango=-3.2, iv_rank=90.0, iv_pctl=82.0)
        assert classify(r) == RegimeClass.STRESS

        b = compute_derived_boundaries(r, SPOT, STEP)
        assert b.default_dte == 30
        assert b.dte_gravity == "near"          # backwardation
        assert b.default_strikes == pytest.approx(24, abs=2)
