"""
tests/test_flow.py — 资金流/持仓分析模块测试

测试覆盖:
- max_pain: 5 个 strike 场景，验证总内在价值最小的 strike
- pcr: Volume PCR 和 OI PCR 计算 + 边界情况
- unusual: vol_oi_ratio 阈值过滤
"""

import pandas as pd
import pytest

from compute.flow.max_pain import compute_max_pain
from compute.flow.pcr import compute_pcr
from compute.flow.unusual import (
    UnusualThresholds,
    detect_unusual,
)
from provider.models import SummaryRecord


# ── Max Pain Tests ──


class TestMaxPain:
    """compute_max_pain: 找到总内在价值最小的 strike。"""

    @pytest.fixture
    def five_strikes(self) -> pd.DataFrame:
        """5 个 strike，put OI 集中在高 strike，call OI 集中在低 strike。

        strike  callOI  putOI
        90      2000    100
        95      1500    300
        100     800     800    ← OI 平衡点，预期 max pain 附近
        105     200     1500
        110     50      2000
        """
        return pd.DataFrame({
            "strike": [90, 95, 100, 105, 110],
            "callOpenInterest": [2000, 1500, 800, 200, 50],
            "putOpenInterest": [100, 300, 800, 1500, 2000],
        })

    def test_returns_strike_and_curve(self, five_strikes: pd.DataFrame):
        mp_strike, curve = compute_max_pain(five_strikes, spot_price=100)
        assert isinstance(mp_strike, float)
        assert isinstance(curve, pd.DataFrame)
        assert set(curve.columns) >= {"strike", "call_pain", "put_pain", "total_pain"}

    def test_curve_has_all_strikes(self, five_strikes: pd.DataFrame):
        _, curve = compute_max_pain(five_strikes, spot_price=100)
        assert len(curve) == 5

    def test_max_pain_is_minimum_total_pain(self, five_strikes: pd.DataFrame):
        """max_pain_strike 应是 pain curve 中 total_pain 最小的行。"""
        mp_strike, curve = compute_max_pain(five_strikes, spot_price=100)
        min_pain_row = curve.loc[curve["total_pain"].idxmin()]
        assert mp_strike == min_pain_row["strike"]

    def test_max_pain_at_balance_point(self, five_strikes: pd.DataFrame):
        """OI 分布对称时 max pain 应在 100 附近。"""
        mp_strike, _ = compute_max_pain(five_strikes, spot_price=100)
        assert mp_strike == 100.0

    def test_pain_at_extremes_is_higher(self, five_strikes: pd.DataFrame):
        """极端 strike (90, 110) 的 total_pain 应高于中间值。"""
        _, curve = compute_max_pain(five_strikes, spot_price=100)
        pain_90 = curve[curve["strike"] == 90]["total_pain"].iloc[0]
        pain_100 = curve[curve["strike"] == 100]["total_pain"].iloc[0]
        pain_110 = curve[curve["strike"] == 110]["total_pain"].iloc[0]
        assert pain_90 > pain_100
        assert pain_110 > pain_100

    def test_manual_calculation(self, five_strikes: pd.DataFrame):
        """手工验证 candidate=95 的 pain:
        call_pain: max(0,95-90)*2000*100 + 0 + 0 + 0 + 0 = 1,000,000
        put_pain:  0 + 0 + max(0,100-95)*800*100 + max(0,105-95)*1500*100 + max(0,110-95)*2000*100
                 = 400,000 + 1,500,000 + 3,000,000 = 4,900,000
        total = 5,900,000
        """
        _, curve = compute_max_pain(five_strikes, spot_price=100)
        row_95 = curve[curve["strike"] == 95].iloc[0]
        assert row_95["call_pain"] == pytest.approx(1_000_000)
        assert row_95["put_pain"] == pytest.approx(4_900_000)
        assert row_95["total_pain"] == pytest.approx(5_900_000)


# ── PCR Tests ──


class TestPCR:
    """compute_pcr: Volume PCR 和 OI PCR。"""

    def test_basic_pcr(self):
        """vol_pcr = pVolu/cVolu, oi_pcr = pOi/cOi。"""
        summary = SummaryRecord(
            ticker="AAPL", tradeDate="2026-04-01",
            cVolu=100_000, pVolu=70_000,
            cOi=500_000, pOi=400_000,
        )
        vol_pcr, oi_pcr = compute_pcr(summary)
        assert vol_pcr == pytest.approx(0.7)
        assert oi_pcr == pytest.approx(0.8)

    def test_pcr_bearish(self):
        """PCR > 1 = 看跌倾向。"""
        summary = SummaryRecord(
            ticker="AAPL", tradeDate="2026-04-01",
            cVolu=50_000, pVolu=80_000,
            cOi=300_000, pOi=450_000,
        )
        vol_pcr, oi_pcr = compute_pcr(summary)
        assert vol_pcr is not None and vol_pcr > 1.0
        assert oi_pcr is not None and oi_pcr > 1.0

    def test_pcr_none_when_missing(self):
        """缺少数据时返回 None。"""
        summary = SummaryRecord(ticker="AAPL", tradeDate="2026-04-01")
        vol_pcr, oi_pcr = compute_pcr(summary)
        assert vol_pcr is None
        assert oi_pcr is None

    def test_pcr_none_when_zero_denominator(self):
        """call volume/OI 为 0 时返回 None（避免除零）。"""
        summary = SummaryRecord(
            ticker="AAPL", tradeDate="2026-04-01",
            cVolu=0, pVolu=1000,
            cOi=0, pOi=500,
        )
        vol_pcr, oi_pcr = compute_pcr(summary)
        assert vol_pcr is None
        assert oi_pcr is None


# ── Unusual Activity Tests ──


class TestUnusual:
    """detect_unusual: 异常期权活动检测。"""

    @pytest.fixture
    def strikes_with_volume(self) -> pd.DataFrame:
        """包含 volume 和 OI 的 strikes 数据。

        strike=100 call: vol=2000, OI=500 → ratio=4.0 (异常)
        strike=105 call: vol=50,   OI=800 → 低成交量，过滤掉
        strike=100 put:  vol=1500, OI=600 → ratio=2.5 (异常 at threshold=2)
        strike=105 put:  vol=100,  OI=900 → ratio=0.11 (正常)
        """
        return pd.DataFrame({
            "strike": [100, 105],
            "callVolume": [2000, 50],
            "callOpenInterest": [500, 800],
            "putVolume": [1500, 100],
            "putOpenInterest": [600, 900],
        })

    def test_filters_by_vol_oi_ratio(self, strikes_with_volume: pd.DataFrame):
        """threshold=2.0 时只返回 ratio >= 2.0 的行。"""
        thresholds = UnusualThresholds(min_volume=100, min_oi=100, vol_oi_ratio=2.0)
        result = detect_unusual(strikes_with_volume, thresholds)
        assert len(result) == 2  # call ratio=4.0, put ratio=2.5
        assert (result["vol_oi_ratio"] >= 2.0).all()

    def test_higher_threshold_fewer_results(self, strikes_with_volume: pd.DataFrame):
        """threshold=3.0 时只返回 ratio >= 3.0 的行。"""
        thresholds = UnusualThresholds(min_volume=100, min_oi=100, vol_oi_ratio=3.0)
        result = detect_unusual(strikes_with_volume, thresholds)
        assert len(result) == 1  # only call ratio=4.0
        assert result.iloc[0]["side"] == "call"

    def test_sorted_by_ratio_descending(self, strikes_with_volume: pd.DataFrame):
        """结果按 vol/oi ratio 降序排列。"""
        thresholds = UnusualThresholds(min_volume=100, min_oi=100, vol_oi_ratio=2.0)
        result = detect_unusual(strikes_with_volume, thresholds)
        assert result["vol_oi_ratio"].is_monotonic_decreasing

    def test_min_volume_filter(self, strikes_with_volume: pd.DataFrame):
        """min_volume=100 过滤掉低成交量的 strike=105 call (vol=50)。"""
        thresholds = UnusualThresholds(min_volume=100, min_oi=100, vol_oi_ratio=0.01)
        result = detect_unusual(strikes_with_volume, thresholds)
        # strike=105 call has vol=50 < 100, should be excluded
        call_results = result[result["side"] == "call"]
        assert all(call_results["volume"] >= 100)

    def test_empty_when_no_match(self):
        """无匹配时返回空 DataFrame。"""
        df = pd.DataFrame({
            "strike": [100],
            "callVolume": [10], "callOpenInterest": [5000],
            "putVolume": [5], "putOpenInterest": [3000],
        })
        result = detect_unusual(df, UnusualThresholds(min_volume=100, min_oi=100, vol_oi_ratio=2.0))
        assert result.empty

    def test_default_thresholds(self, strikes_with_volume: pd.DataFrame):
        """默认阈值 (min_volume=100, min_oi=500, vol_oi_ratio=3.0)。"""
        result = detect_unusual(strikes_with_volume)
        # Default vol_oi_ratio=3.0: only call ratio=4.0 qualifies
        assert len(result) == 1
        assert result.iloc[0]["vol_oi_ratio"] == pytest.approx(4.0)

    def test_side_column_present(self, strikes_with_volume: pd.DataFrame):
        """结果应包含 side 列标注 call/put。"""
        thresholds = UnusualThresholds(min_volume=100, min_oi=100, vol_oi_ratio=2.0)
        result = detect_unusual(strikes_with_volume, thresholds)
        assert "side" in result.columns
        assert set(result["side"]) <= {"call", "put"}
