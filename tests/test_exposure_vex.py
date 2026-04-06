"""
tests/test_exposure_vex.py — VEX 计算 + 聚合维度 + 缩放函数单元测试

测试覆盖:
- VEX: call 和 put vega 同号（KEEP_SIGN）
- 三种聚合维度: by_strike / by_expiry / notional
- 缩放函数数值正确性

GEX + DEX 测试见 test_exposure.py
"""

import pandas as pd
import pytest

from compute.exposure import (
    ExposureFrame,
    compute_gex,
    compute_vex,
    GAMMA_EXPOSURE,
    DELTA_EXPOSURE,
    VEGA_EXPOSURE,
)
from provider.models import StrikesFrame


# ── Fixtures ──

@pytest.fixture
def mock_strikes() -> StrikesFrame:
    """3 个 strike × 2 个到期日 = 6 行 mock 数据 (spot=100)。"""
    return StrikesFrame(df=pd.DataFrame({
        "strike":            [95, 100, 105,  95, 100, 105],
        "spotPrice":         [100, 100, 100, 100, 100, 100],
        "expirDate":         ["2026-04-18"] * 3 + ["2026-05-16"] * 3,
        "dte":               [17, 17, 17, 45, 45, 45],
        "gamma":             [0.04, 0.05, 0.03, 0.03, 0.04, 0.02],
        "delta":             [0.70, 0.50, 0.30, 0.65, 0.50, 0.35],
        "vega":              [0.10, 0.15, 0.08, 0.12, 0.18, 0.10],
        "callOpenInterest":  [1000, 2000, 500,  800, 1500, 400],
        "putOpenInterest":   [600, 1000, 1500,  500, 800, 1200],
    }))


# ── VEX Tests ──

class TestVEX:
    """VEX 计算测试: vega × OI × 100, call/put 同号。"""

    def test_vex_both_sides_positive(self, mock_strikes: StrikesFrame):
        """Vega 同号: call 和 put exposure 都应为正。"""
        result = compute_vex(mock_strikes)
        assert (result.df["call_exposure"] >= 0).all()
        assert (result.df["put_exposure"] >= 0).all()

    def test_vex_first_row_manual(self, mock_strikes: StrikesFrame):
        """手工验证第一行 (strike=95, vega=0.10):
        scale = 100
        call = 0.10 × 1000 × 100 = 10,000
        put  = 0.10 × 600  × 100 = 6,000
        net  = 16,000
        """
        result = compute_vex(mock_strikes)
        row = result.df.iloc[0]
        assert abs(row["call_exposure"] - 10_000) < 0.01
        assert abs(row["put_exposure"] - 6_000) < 0.01
        assert abs(row["exposure_value"] - 16_000) < 0.01

    def test_vex_no_sign_flip(self):
        """验证 VEX 不翻转 put 符号 (KEEP_SIGN)。"""
        df = pd.DataFrame({
            "strike": [100], "spotPrice": [100],
            "vega": [0.20],
            "callOpenInterest": [0], "putOpenInterest": [500],
            "expirDate": ["2026-04-18"], "dte": [17],
        })
        sf = StrikesFrame(df=df)
        result = compute_vex(sf)
        # put_exposure = 0.20 × 500 × 100 = 10,000 (正数)
        assert result.df.iloc[0]["put_exposure"] == pytest.approx(10_000)


# ── Aggregation Tests ──

class TestAggregation:
    """三种聚合维度: by_strike (gexr), by_expiry (gexs), notional (gexn)。"""

    def test_aggregate_by_strike(self, mock_strikes: StrikesFrame):
        """gexr: 按 strike 聚合所有到期日。"""
        result = compute_gex(mock_strikes)
        by_strike = result.df.groupby("strike")["exposure_value"].sum()
        # 3 个 unique strike
        assert len(by_strike) == 3
        assert set(by_strike.index) == {95, 100, 105}

    def test_aggregate_by_expiry(self, mock_strikes: StrikesFrame):
        """gexs: 按 expirDate 聚合所有 strike。"""
        result = compute_gex(mock_strikes)
        by_expiry = result.df.groupby("expirDate")["exposure_value"].sum()
        # 2 个到期日
        assert len(by_expiry) == 2
        assert set(by_expiry.index) == {"2026-04-18", "2026-05-16"}

    def test_aggregate_notional(self, mock_strikes: StrikesFrame):
        """gexn: 全量求和得到单一净暴露值。"""
        result = compute_gex(mock_strikes)
        notional = result.df["exposure_value"].sum()
        # 验证是 float 标量
        assert isinstance(notional, float)

    def test_notional_equals_sum_of_strikes(self, mock_strikes: StrikesFrame):
        """Notional 应等于所有 by_strike 之和。"""
        result = compute_gex(mock_strikes)
        notional = result.df["exposure_value"].sum()
        by_strike_sum = result.df.groupby("strike")["exposure_value"].sum().sum()
        assert abs(notional - by_strike_sum) < 0.01

    def test_notional_equals_sum_of_expiry(self, mock_strikes: StrikesFrame):
        """Notional 应等于所有 by_expiry 之和。"""
        result = compute_gex(mock_strikes)
        notional = result.df["exposure_value"].sum()
        by_expiry_sum = (
            result.df.groupby("expirDate")["exposure_value"].sum().sum()
        )
        assert abs(notional - by_expiry_sum) < 0.01

    def test_dimension_columns_preserved(self, mock_strikes: StrikesFrame):
        """ExposureFrame 应保留 strike, expirDate, dte 维度列。"""
        result = compute_gex(mock_strikes)
        assert "strike" in result.df.columns
        assert "expirDate" in result.df.columns
        assert "dte" in result.df.columns


# ── Scaling Function Tests ──

class TestScalingFunctions:
    """缩放函数单元测试。"""

    def test_gamma_exposure_at_100(self):
        assert GAMMA_EXPOSURE(100) == 100 ** 2 * 0.01 * 100  # 10,000

    def test_gamma_exposure_at_200(self):
        assert GAMMA_EXPOSURE(200) == 200 ** 2 * 0.01 * 100  # 40,000

    def test_delta_exposure_at_100(self):
        assert DELTA_EXPOSURE(100) == 100 * 100  # 10,000

    def test_vega_exposure_constant(self):
        # Vega 缩放不依赖 spot
        assert VEGA_EXPOSURE(100) == 100
        assert VEGA_EXPOSURE(500) == 100
