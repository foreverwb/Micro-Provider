"""
tests/test_integration.py — GEX / IV Surface / GEX Surface / Regime Pipeline 集成测试

验证 provider → compute → output 的完整数据流，使用 conftest 中的
mock_orats_provider 替代真实 HTTP 请求。

测试覆盖:
1. GEX pipeline: provider → compute_gex → ExposureFrame (按 strike 聚合)
2. IV Surface pipeline: provider → SurfaceBuilder → SurfaceFrame(DELTA)
3. GEX Surface pipeline: 验证内部路由到 compute_exposure，无重复计算逻辑
4. Regime → Boundary pipeline: classify() + compute_derived_boundaries()

高分歧 Regime + Snap 编排测试见 test_integration_snap.py
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from compute.exposure import (
    ExposureFrame,
    compute_exposure,
    compute_gex,
)
from compute.volatility.models import CoordType, SurfaceFrame
from compute.volatility.surface import SurfaceBuilder
from regime.boundary import (
    RegimeClass,
    MarketRegime,
    classify,
    compute_derived_boundaries,
)


# ── 1. GEX Pipeline ──


class TestGEXPipeline:
    """GEX 完整 pipeline: provider → compute_gex → ExposureFrame (按 strike 聚合)。"""

    @pytest.mark.asyncio
    async def test_gexr_pipeline(self, mock_orats_provider):
        """GEX by-strike (gexr) pipeline: 从 provider 获取 strikes → 计算 GEX → 聚合。"""
        # Step 1: 通过 provider 获取标准化 strikes 数据
        strikes = await mock_orats_provider.get_strikes("AAPL")

        # Step 2: 计算 GEX（调用 compute/ 子包，不在此处重新实现公式）
        result = compute_gex(strikes)

        # Step 3: 验证输出结构
        assert isinstance(result, ExposureFrame)
        assert "exposure_value" in result.df.columns
        assert "call_exposure" in result.df.columns
        assert "put_exposure" in result.df.columns
        assert "strike" in result.df.columns
        assert "expirDate" in result.df.columns

        # Step 4: 按 strike 聚合（gexr 维度）
        by_strike = result.df.groupby("strike")["exposure_value"].sum()
        assert len(by_strike) > 0
        # 30 行数据（3 expiries × 10 strikes）→ 10 个 unique strike
        assert len(by_strike) == 10
        # 验证有非零暴露（mock 数据的 gamma/OI 均为正值）
        assert by_strike.abs().sum() > 0

    @pytest.mark.asyncio
    async def test_gex_call_positive_put_negative(self, mock_orats_provider):
        """GEX call 侧为正，put 侧取反后为负。"""
        strikes = await mock_orats_provider.get_strikes("AAPL")
        result = compute_gex(strikes)
        assert (result.df["call_exposure"] >= 0).all()
        assert (result.df["put_exposure"] <= 0).all()

    @pytest.mark.asyncio
    async def test_gex_notional(self, mock_orats_provider):
        """全市场净 GEX notional = 所有 strike 的 exposure_value 之和。"""
        strikes = await mock_orats_provider.get_strikes("AAPL")
        result = compute_gex(strikes)
        notional = result.df["exposure_value"].sum()
        # notional 是标量 float
        assert isinstance(float(notional), float)
        # by_strike 之和 == by_expiry 之和 == notional（聚合一致性）
        by_strike_total = result.df.groupby("strike")["exposure_value"].sum().sum()
        assert abs(notional - by_strike_total) < 0.01


# ── 2. IV Surface Pipeline ──


class TestIVSurfacePipeline:
    """IV Surface pipeline: provider → SurfaceBuilder → SurfaceFrame(DELTA 坐标)。"""

    @pytest.mark.asyncio
    async def test_surface_iv_pipeline(self, mock_orats_provider):
        """IV 曲面应使用 delta 坐标系。"""
        monies = await mock_orats_provider.get_monies("AAPL")
        sf = SurfaceBuilder.build("iv", monies)

        # IV 域曲面 X 轴为 delta
        assert isinstance(sf, SurfaceFrame)
        assert sf.coord_type == CoordType.DELTA
        assert sf.x_axis == "delta"

    @pytest.mark.asyncio
    async def test_iv_surface_shape(self, mock_orats_provider):
        """5 个到期日 × 21 delta 采样点。"""
        monies = await mock_orats_provider.get_monies("AAPL")
        sf = SurfaceBuilder.build("iv", monies)
        # mock_monies_df 有 5 个到期日，vol0~vol100 步长 5 = 21 个 delta 点
        assert sf.data.shape == (5, 21)

    @pytest.mark.asyncio
    async def test_iv_surface_values_positive(self, mock_orats_provider):
        """IV 值应全为正（波动率不可为负）。"""
        monies = await mock_orats_provider.get_monies("AAPL")
        sf = SurfaceBuilder.build("iv", monies)
        assert (sf.data > 0).all().all()


# ── 3. GEX Surface Pipeline ──


class TestGEXSurfacePipeline:
    """GEX Surface pipeline: 验证内部路由到 compute_exposure，不重复计算。"""

    @pytest.mark.asyncio
    async def test_surface_gex_pipeline_coord_type(self, mock_orats_provider):
        """GEX 曲面应使用 strike 坐标系（Greeks 域）。"""
        strikes = await mock_orats_provider.get_strikes("AAPL")
        sf = SurfaceBuilder.build("gex", strikes)

        assert isinstance(sf, SurfaceFrame)
        assert sf.coord_type == CoordType.STRIKE
        assert sf.x_axis == "strike"

    @pytest.mark.asyncio
    async def test_surface_gex_routes_through_compute_exposure(
        self, mock_orats_provider
    ):
        """验证 SurfaceBuilder 内部通过 compute_exposure() 计算 GEX，
        而不是在 surface.py 中重新实现 GEX 公式（设计约束: 单一计算路径）。
        """
        strikes = await mock_orats_provider.get_strikes("AAPL")

        # 用 wraps 包装真实函数: 既验证调用，又保留正常计算
        with patch(
            "compute.volatility.surface.compute_exposure",
            wraps=compute_exposure,
        ) as mock_ce:
            sf = SurfaceBuilder.build("gex", strikes)
            # compute_exposure 必须被调用过（而非 surface.py 自行计算）
            assert mock_ce.called, (
                "SurfaceBuilder 应通过 compute_exposure() 计算 GEX，"
                "而不是在 surface.py 中重新实现公式"
            )

        # 验证输出量级: GEX 值远大于原始 gamma（0.01~0.05 量级）
        assert sf.data.abs().max().max() > 1000
        assert sf.z_label == "GEX $"

    @pytest.mark.asyncio
    async def test_surface_gex_shape(self, mock_orats_provider):
        """GEX 曲面行数 = DTE 数量，列数 = unique strike 数量。"""
        strikes = await mock_orats_provider.get_strikes("AAPL")
        sf = SurfaceBuilder.build("gex", strikes)
        n_expiries = strikes.df["dte"].nunique()
        n_strikes = strikes.df["strike"].nunique()
        assert sf.data.shape == (n_expiries, n_strikes)


# ── 4. Regime → Boundary Pipeline ──


class TestRegimeBoundaryPipeline:
    """Regime → Boundary 完整 pipeline: classify() + compute_derived_boundaries()。"""

    def test_regime_to_boundary_pipeline(self):
        """标准 NORMAL 场景: iv30d=22%, IVR=48, IVP=52, contango=1.8。"""
        regime = MarketRegime(
            iv30d=0.22,
            iv_rank=48.0,
            iv_pctl=52.0,
            contango=1.8,
            vol_of_vol=0.05,
            vrp=3.2,
        )

        # Step 1: classify
        regime_class = classify(regime)
        assert regime_class == RegimeClass.NORMAL

        # Step 2: compute_derived_boundaries (AAPL: spot=218.50, step=$2.50)
        bounds = compute_derived_boundaries(regime, spot_price=218.50, est_strike_step=2.5)
        assert bounds.default_dte == 60          # contango ∈ (-2, +2) → balanced
        assert bounds.dte_gravity == "balanced"
        assert bounds.confidence == "HIGH"       # divergence=4 < 30

    def test_boundary_return_type(self):
        """compute_derived_boundaries 返回 DerivedBoundaries 实例。"""
        from regime.boundary import DerivedBoundaries
        r = MarketRegime(
            iv30d=0.22, iv_rank=48.0, iv_pctl=52.0,
            contango=1.0, vol_of_vol=0.05, vrp=0.03,
        )
        b = compute_derived_boundaries(r, 218.50, 2.5)
        assert isinstance(b, DerivedBoundaries)

    def test_pipeline_stress_scenario(self):
        """STRESS 场景 (backwardation): default_dte=30, dte_gravity='near'。"""
        regime = MarketRegime(
            iv30d=0.38, iv_rank=90.0, iv_pctl=82.0,
            contango=-3.2, vol_of_vol=0.08, vrp=0.05,
        )
        assert classify(regime) == RegimeClass.STRESS
        bounds = compute_derived_boundaries(regime, 218.50, 2.5)
        assert bounds.default_dte == 30
        assert bounds.dte_gravity == "near"
