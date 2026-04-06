"""
tests/test_integration_snap.py — 高分歧 Regime + Snap 编排集成测试

测试覆盖:
5. 高分歧 Regime: confidence=LOW + sigma_multiplier ×1.1
6. Snap 编排: 多个 compute/ 子包协同完成完整 snapshot 计算

GEX / IV Surface / GEX Surface / Regime 基础 Pipeline 见 test_integration.py
"""

from __future__ import annotations

import pytest

from compute.exposure import compute_gex
from compute.flow.pcr import compute_pcr
from compute.volatility.models import TermFrame
from compute.volatility.surface import SurfaceBuilder
from compute.volatility.term import TermBuilder
from regime.boundary import (
    RegimeClass,
    MarketRegime,
    classify,
    compute_derived_boundaries,
)


# ── 5. Regime 高分歧 Pipeline ──


class TestHighDivergencePipeline:
    """高分歧 Regime (IVR/IVP 分歧度 > 30) 的完整处理路径。"""

    def test_regime_high_divergence(self):
        """IVR=23, IVP=78: iv_divergence=55 > 30 → confidence=LOW。"""
        regime = MarketRegime(
            iv30d=0.22,
            iv_rank=23.0,
            iv_pctl=78.0,
            contango=1.0,
            vol_of_vol=0.05,
            vrp=0.03,
        )
        # iv_divergence = |23 - 78| = 55
        assert regime.iv_divergence == pytest.approx(55.0)
        assert regime.iv_divergence > 30

    def test_high_divergence_sigma_multiplier(self):
        """高分歧时 sigma_multiplier 应被 ×1.1 扩宽（覆盖更多尾部风险）。"""
        regime = MarketRegime(
            iv30d=0.22,
            iv_rank=23.0,
            iv_pctl=78.0,
            contango=1.0,
            vol_of_vol=0.05,
            vrp=0.03,
        )
        # iv_consensus = 0.4×23 + 0.6×78 = 56.0 → 正常 sigma_multiplier = 2.0
        # 高分歧 → ×1.1 = 2.2
        bounds = compute_derived_boundaries(regime, 218.50, 2.5)
        assert bounds.sigma_multiplier == pytest.approx(2.0 * 1.1, rel=0.01)

    def test_high_divergence_confidence_low(self):
        """高分歧 → confidence='LOW'，提示下游调用方谨慎使用分类结果。"""
        regime = MarketRegime(
            iv30d=0.22,
            iv_rank=23.0,
            iv_pctl=78.0,
            contango=1.0,
            vol_of_vol=0.05,
            vrp=0.03,
        )
        bounds = compute_derived_boundaries(regime, 218.50, 2.5)
        assert bounds.confidence == "LOW"

    def test_high_divergence_still_normal_regime(self):
        """高分歧不改变 regime 分类本身，只影响边界参数。"""
        regime = MarketRegime(
            iv30d=0.22,
            iv_rank=23.0,
            iv_pctl=78.0,
            contango=1.0,
            vol_of_vol=0.05,
            vrp=0.03,
        )
        # iv_consensus = 56, iv30d=0.22 → NORMAL
        assert classify(regime) == RegimeClass.NORMAL


# ── 6. Snap 编排 Pipeline ──


class TestSnapOrchestration:
    """Snap 快照编排: 验证多个 compute/ 子包协同，单一计算路径无重复实现。"""

    @pytest.mark.asyncio
    async def test_snap_full_pipeline(
        self,
        mock_orats_provider,
        mock_strikes_frame,
        mock_monies_frame,
        mock_summary_record,
    ):
        """模拟 snap 命令的完整计算编排:
        1. GEX notional (compute/exposure)
        2. PCR (compute/flow)
        3. Term structure (compute/volatility)
        所有结果来自 compute/ 子包，不在编排层重新实现计算逻辑。
        """
        # ── GEX notional (compute/exposure) ──
        strikes = await mock_orats_provider.get_strikes("AAPL")
        gex_result = compute_gex(strikes)
        gex_notional = float(gex_result.df["exposure_value"].sum())

        # ── PCR (compute/flow) ──
        summary = await mock_orats_provider.get_summary("AAPL")
        vol_pcr, oi_pcr = compute_pcr(summary)

        # ── Term structure (compute/volatility) ──
        monies = await mock_orats_provider.get_monies("AAPL")
        tf = TermBuilder.build(monies)

        # ── 验证各模块结果均有效 ──
        assert isinstance(gex_notional, float)
        assert abs(gex_notional) > 0

        assert vol_pcr is not None
        assert oi_pcr is not None
        assert vol_pcr > 0
        assert oi_pcr > 0

        assert isinstance(tf, TermFrame)
        assert len(tf.df) > 0
        assert "atmiv" in tf.df.columns

    @pytest.mark.asyncio
    async def test_snap_module_origins(
        self,
        mock_orats_provider,
        mock_strikes_frame,
        mock_monies_frame,
        mock_summary_record,
    ):
        """验证各计算函数来自 compute/ 子包（模块路径一致性检查）。"""
        # compute_gex 来自 compute.exposure
        assert "compute.exposure" in compute_gex.__module__

        # compute_pcr 来自 compute.flow
        assert "compute.flow" in compute_pcr.__module__

        # TermBuilder 来自 compute.volatility
        assert "compute.volatility" in TermBuilder.__module__

        # SurfaceBuilder 来自 compute.volatility
        assert "compute.volatility" in SurfaceBuilder.__module__

    @pytest.mark.asyncio
    async def test_snap_gex_by_expiry(self, mock_orats_provider):
        """GEX by-expiry (gexs 维度) 聚合与 by-strike 总量一致。"""
        strikes = await mock_orats_provider.get_strikes("AAPL")
        result = compute_gex(strikes)

        by_expiry = result.df.groupby("expirDate")["exposure_value"].sum()
        by_strike = result.df.groupby("strike")["exposure_value"].sum()

        # 3 个到期日
        assert len(by_expiry) == 3
        # 总量一致（两种聚合维度之和相同）
        assert abs(by_expiry.sum() - by_strike.sum()) < 0.01

    @pytest.mark.asyncio
    async def test_snap_iv_surface_and_term_consistent(self, mock_orats_provider):
        """IV surface 的 ATM IV 与 term structure 的 atmiv 应来自同一数据源，数值一致。"""
        monies = await mock_orats_provider.get_monies("AAPL")

        # Term structure ATM IV（每个到期日一个值）
        tf = TermBuilder.build(monies)
        term_atmivs = tf.df.set_index("dte")["atmiv"].to_dict()

        # IV surface 在 delta=50（ATM）列的值
        sf = SurfaceBuilder.build("iv", monies)
        # delta=50 对应 vol50 列
        surface_atm = sf.data[50]  # 按 delta=50 取列

        # 两者应一致（同源数据）
        for dte, atmiv in term_atmivs.items():
            if dte in surface_atm.index:
                assert surface_atm[dte] == pytest.approx(atmiv, rel=1e-3)
