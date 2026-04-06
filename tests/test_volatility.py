"""
tests/test_volatility.py — MetricRegistry + SurfaceBuilder 测试

测试覆盖:
- MetricRegistry 路由: IV 域 vs Greeks 域正确分发
- UnknownMetricError 异常
- SurfaceBuilder: coord_type 路由 + 类型校验

TermBuilder / SkewBuilder / SmileBuilder 测试见 test_volatility_builders.py
"""

import pandas as pd
import pytest

from compute.volatility.registry import (
    METRIC_REGISTRY,
    DataSource,
    MetricDef,
    StrategyType,
    UnknownMetricError,
    lookup,
)
from compute.volatility.models import (
    CoordType,
    SkewFrame,
    SmileFrame,
    SurfaceFrame,
    TermFrame,
)
from compute.volatility.surface import SurfaceBuilder
from compute.volatility.term import TermBuilder
from compute.volatility.skew import SkewBuilder
from compute.volatility.smile import SmileBuilder
from provider.models import MoniesFrame, StrikesFrame, SummaryRecord


# ── Fixtures ──


@pytest.fixture
def mock_monies() -> MoniesFrame:
    """3 个到期日的 MoniesFrame mock 数据。"""
    vol_data = {
        f"vol{i}": [0.20 + i * 0.001, 0.22 + i * 0.001, 0.25 + i * 0.001]
        for i in range(0, 101, 5)
    }
    vol_data.update({
        "atmiv": [0.25, 0.27, 0.30],
        "slope": [-0.10, -0.12, -0.15],
        "deriv": [0.01, 0.012, 0.015],
        "dte": [17, 45, 90],
        "expirDate": ["2026-04-18", "2026-05-16", "2026-06-19"],
        "spotPrice": [218.5, 218.5, 218.5],
    })
    return MoniesFrame(df=pd.DataFrame(vol_data))


@pytest.fixture
def mock_strikes() -> StrikesFrame:
    """3 strikes × 2 expiries = 6 行 mock 数据。"""
    return StrikesFrame(df=pd.DataFrame({
        "strike": [210, 215, 220, 210, 215, 220],
        "spotPrice": [218.5] * 6,
        "expirDate": ["2026-04-18"] * 3 + ["2026-05-16"] * 3,
        "dte": [17, 17, 17, 45, 45, 45],
        "gamma": [0.04, 0.05, 0.03, 0.03, 0.04, 0.025],
        "delta": [0.60, 0.50, 0.40, 0.58, 0.50, 0.42],
        "vega": [0.12, 0.15, 0.10, 0.14, 0.18, 0.12],
        "callOpenInterest": [1000, 2000, 800, 600, 1500, 500],
        "putOpenInterest": [700, 1200, 1500, 500, 900, 1100],
        "callMidIv": [0.28, 0.25, 0.23, 0.30, 0.27, 0.25],
        "putMidIv": [0.29, 0.26, 0.24, 0.31, 0.28, 0.26],
        "smvVol": [0.275, 0.252, 0.235, 0.300, 0.275, 0.255],
    }))


# ── MetricRegistry Tests ──


class TestMetricRegistry:
    """MetricRegistry 路由测试。"""

    def test_iv_domain_routes_to_iv_surface(self):
        """iv, smvVol, ivask, calVol, earnEffect → MONIES + IV_SURFACE。"""
        iv_metrics = ["iv", "smvVol", "ivask", "calVol", "earnEffect"]
        for name in iv_metrics:
            mdef = lookup(name)
            assert mdef.source == DataSource.MONIES, f"{name} source wrong"
            assert mdef.strategy == StrategyType.IV_SURFACE, f"{name} strategy wrong"
            assert mdef.requires_oi is False, f"{name} should not require OI"

    def test_greek_domain_routes_to_greek_surface(self):
        """gamma, delta, vega, theta → STRIKES + GREEK_SURFACE, no OI。"""
        greek_metrics = ["gamma", "delta", "vega", "theta"]
        for name in greek_metrics:
            mdef = lookup(name)
            assert mdef.source == DataSource.STRIKES, f"{name} source wrong"
            assert mdef.strategy == StrategyType.GREEK_SURFACE, f"{name} strategy wrong"
            assert mdef.requires_oi is False, f"{name} should not require OI"

    def test_exposure_domain_requires_oi(self):
        """gex, dex, vex → STRIKES + GREEK_SURFACE + requires_oi=True。"""
        exposure_metrics = ["gex", "dex", "vex"]
        for name in exposure_metrics:
            mdef = lookup(name)
            assert mdef.source == DataSource.STRIKES, f"{name} source wrong"
            assert mdef.strategy == StrategyType.GREEK_SURFACE, f"{name} strategy wrong"
            assert mdef.requires_oi is True, f"{name} should require OI"

    def test_total_registry_count(self):
        """注册表共 12 个 metric (5 IV + 4 Greeks + 3 Exposure)。"""
        assert len(METRIC_REGISTRY) == 12

    def test_unknown_metric_raises(self):
        """未注册 metric 抛出 UnknownMetricError。"""
        with pytest.raises(UnknownMetricError) as exc_info:
            lookup("nonexistent_metric")
        assert "nonexistent_metric" in str(exc_info.value)

    def test_unknown_metric_lists_available(self):
        """错误信息包含可用 metric 列表。"""
        with pytest.raises(UnknownMetricError) as exc_info:
            lookup("bad")
        # 至少包含 iv 和 gex
        msg = str(exc_info.value)
        assert "iv" in msg
        assert "gex" in msg


# ── SurfaceBuilder Routing Tests ──


class TestSurfaceBuilder:
    """SurfaceBuilder 路由与类型校验。"""

    def test_iv_surface_returns_delta_coord(self, mock_monies: MoniesFrame):
        sf = SurfaceBuilder.build("iv", mock_monies)
        assert sf.coord_type == CoordType.DELTA
        assert sf.x_axis == "delta"

    def test_greek_surface_returns_strike_coord(self, mock_strikes: StrikesFrame):
        sf = SurfaceBuilder.build("gamma", mock_strikes)
        assert sf.coord_type == CoordType.STRIKE
        assert sf.x_axis == "strike"

    def test_iv_surface_shape(self, mock_monies: MoniesFrame):
        """IV surface: 3 expiries × 21 delta points。"""
        sf = SurfaceBuilder.build("iv", mock_monies)
        assert sf.data.shape == (3, 21)

    def test_gex_surface_calls_compute_exposure(self, mock_strikes: StrikesFrame):
        """GEX surface 应通过 compute_exposure 产生 exposure 值，非原始 gamma。"""
        sf = SurfaceBuilder.build("gex", mock_strikes)
        assert sf.z_label == "GEX $"
        # GEX 值量级远大于原始 gamma (0.01~0.05)
        assert sf.data.abs().max().max() > 1000

    def test_type_mismatch_iv_with_strikes(self, mock_strikes: StrikesFrame):
        with pytest.raises(TypeError, match="MoniesFrame"):
            SurfaceBuilder.build("iv", mock_strikes)

    def test_type_mismatch_greek_with_monies(self, mock_monies: MoniesFrame):
        with pytest.raises(TypeError, match="StrikesFrame"):
            SurfaceBuilder.build("gamma", mock_monies)
