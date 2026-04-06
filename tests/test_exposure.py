"""
tests/test_exposure.py — GEX/DEX 计算正确性测试

测试覆盖:
- GEX: call 侧为正、put 侧取反后为负、手工公式验证
- DEX: put delta = call_delta - 1，KEEP_SIGN 无额外取反

VEX + 聚合维度 + 缩放函数单元测试见 test_exposure_vex.py
"""

import pandas as pd
import pytest

from compute.exposure import (
    ExposureFrame,
    SignConvention,
    compute_dex,
    compute_exposure,
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
    """3 个 strike × 2 个到期日 = 6 行 mock 数据。

    spot=100 便于手工验证:
    - GAMMA_EXPOSURE(100) = 100² × 0.01 × 100 = 10,000
    - DELTA_EXPOSURE(100) = 100 × 100 = 10,000
    - VEGA_EXPOSURE(100) = 100
    """
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


# ── GEX Tests ──

class TestGEX:
    """GEX 计算测试: gamma × OI × spot² × 0.01 × 100, put 侧取反。"""

    def test_gex_returns_exposure_frame(self, mock_strikes: StrikesFrame):
        result = compute_gex(mock_strikes)
        assert isinstance(result, ExposureFrame)
        assert "exposure_value" in result.df.columns

    def test_gex_call_positive(self, mock_strikes: StrikesFrame):
        """Call 侧 GEX 应为正值（gamma 和 OI 都为正）。"""
        result = compute_gex(mock_strikes)
        assert (result.df["call_exposure"] >= 0).all()

    def test_gex_put_negative(self, mock_strikes: StrikesFrame):
        """Put 侧 GEX 应为负值（NEGATE_PUT 取反后）。"""
        result = compute_gex(mock_strikes)
        assert (result.df["put_exposure"] <= 0).all()

    def test_gex_first_row_manual(self, mock_strikes: StrikesFrame):
        """手工验证第一行 (strike=95, expiry=04-18):
        scale = 100² × 0.01 × 100 = 10,000
        call = 0.04 × 1000 × 10000 = 400,000
        put  = 0.04 × 600  × 10000 × (-1) = -240,000
        net  = 160,000
        """
        result = compute_gex(mock_strikes)
        row = result.df.iloc[0]
        assert abs(row["call_exposure"] - 400_000) < 0.01
        assert abs(row["put_exposure"] - (-240_000)) < 0.01
        assert abs(row["exposure_value"] - 160_000) < 0.01

    def test_gex_uses_negate_put(self):
        """验证 compute_gex 使用 NEGATE_PUT 符号约定。"""
        # 通过 compute_exposure 直接调用对比
        df = pd.DataFrame({
            "strike": [100], "spotPrice": [100],
            "gamma": [0.05],
            "callOpenInterest": [0], "putOpenInterest": [1000],
            "expirDate": ["2026-04-18"], "dte": [17],
        })
        sf = StrikesFrame(df=df)

        result = compute_gex(sf)
        # put only: 0.05 × 1000 × 10000 × (-1) = -500,000
        assert result.df.iloc[0]["put_exposure"] < 0


# ── DEX Tests ──

class TestDEX:
    """DEX 计算测试: delta × OI × spot × 100, put delta 已为负。"""

    def test_dex_put_delta_negative(self, mock_strikes: StrikesFrame):
        """Put delta = call_delta - 1，应产生负的 put exposure。

        第一行: call_delta=0.70, put_delta=0.70-1=-0.30
        put_exposure = -0.30 × 600 × 10000 = -1,800,000
        """
        result = compute_dex(mock_strikes)
        row = result.df.iloc[0]
        expected_put = (0.70 - 1) * 600 * 10_000  # -1,800,000
        assert abs(row["put_exposure"] - expected_put) < 0.01

    def test_dex_call_exposure_positive_for_itm(self, mock_strikes: StrikesFrame):
        """ITM call (delta=0.70>0.5) 的 call exposure 应为正。"""
        result = compute_dex(mock_strikes)
        row = result.df.iloc[0]  # delta=0.70
        assert row["call_exposure"] > 0

    def test_dex_first_row_manual(self, mock_strikes: StrikesFrame):
        """手工验证第一行 (strike=95, delta=0.70):
        scale = 100 × 100 = 10,000
        call = 0.70 × 1000 × 10000 = 7,000,000
        put  = (0.70-1) × 600 × 10000 = -1,800,000
        net  = 5,200,000
        """
        result = compute_dex(mock_strikes)
        row = result.df.iloc[0]
        assert abs(row["call_exposure"] - 7_000_000) < 0.01
        assert abs(row["put_exposure"] - (-1_800_000)) < 0.01
        assert abs(row["exposure_value"] - 5_200_000) < 0.01

    def test_dex_atm_put_delta_minus_half(self, mock_strikes: StrikesFrame):
        """ATM (delta=0.50) 的 put delta 应为 -0.50。"""
        result = compute_dex(mock_strikes)
        # 第二行: delta=0.50, putOI=1000
        row = result.df.iloc[1]
        expected_put = (0.50 - 1) * 1000 * 10_000  # -5,000,000
        assert abs(row["put_exposure"] - expected_put) < 0.01
