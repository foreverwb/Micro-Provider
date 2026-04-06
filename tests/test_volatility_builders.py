"""
tests/test_volatility_builders.py — TermBuilder / SkewBuilder / SmileBuilder 测试

测试覆盖:
- TermBuilder: 1D 期限结构构建 + forecast overlay
- SkewBuilder: delta 坐标切片 + compare 叠加
- SmileBuilder: strike 坐标切片 + contract_filter + SMV overlay

MetricRegistry + SurfaceBuilder 测试见 test_volatility.py
"""

import pandas as pd
import pytest

from compute.volatility.models import (
    SkewFrame,
    SmileFrame,
    TermFrame,
)
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


@pytest.fixture
def mock_summary() -> SummaryRecord:
    """带 M1~M4 forecast 的 SummaryRecord。"""
    return SummaryRecord(
        ticker="AAPL", tradeDate="2026-04-01",
        dtExM1=17, atmFcstIvM1=0.24,
        dtExM2=45, atmFcstIvM2=0.26,
        dtExM3=90, atmFcstIvM3=0.29,
        dtExM4=120, atmFcstIvM4=0.31,
    )


# ── TermBuilder Tests ──


class TestTermBuilder:
    """TermBuilder: 1D 期限结构。"""

    def test_basic_term_structure(self, mock_monies: MoniesFrame):
        tf = TermBuilder.build(mock_monies)
        assert isinstance(tf, TermFrame)
        assert "dte" in tf.df.columns
        assert "atmiv" in tf.df.columns

    def test_sorted_by_dte(self, mock_monies: MoniesFrame):
        """输出应按 DTE 升序排列（近月在前）。"""
        tf = TermBuilder.build(mock_monies)
        assert tf.df["dte"].is_monotonic_increasing

    def test_row_count_matches_expiries(self, mock_monies: MoniesFrame):
        """每个到期日一行。"""
        tf = TermBuilder.build(mock_monies)
        assert len(tf.df) == 3

    def test_atmiv_values_preserved(self, mock_monies: MoniesFrame):
        """ATM IV 值应与输入一致。"""
        tf = TermBuilder.build(mock_monies)
        assert list(tf.df["atmiv"]) == [0.25, 0.27, 0.30]

    def test_overlay_adds_forecast_column(
        self, mock_monies: MoniesFrame, mock_summary: SummaryRecord
    ):
        """overlay=True 应添加 forecast_iv 列。"""
        tf = TermBuilder.build(mock_monies, summary_record=mock_summary, overlay=True)
        assert "forecast_iv" in tf.df.columns

    def test_overlay_forecast_values_match(
        self, mock_monies: MoniesFrame, mock_summary: SummaryRecord
    ):
        """forecast_iv 应按 DTE 与 SummaryRecord 的 M1~M4 对齐。"""
        tf = TermBuilder.build(mock_monies, summary_record=mock_summary, overlay=True)
        # dte=17 → M1 forecast=0.24
        row_17 = tf.df[tf.df["dte"] == 17].iloc[0]
        assert row_17["forecast_iv"] == pytest.approx(0.24)
        # dte=45 → M2 forecast=0.26
        row_45 = tf.df[tf.df["dte"] == 45].iloc[0]
        assert row_45["forecast_iv"] == pytest.approx(0.26)

    def test_no_overlay_no_forecast_column(self, mock_monies: MoniesFrame):
        """overlay=False 时不应有 forecast_iv 列。"""
        tf = TermBuilder.build(mock_monies)
        assert "forecast_iv" not in tf.df.columns


# ── SkewBuilder Tests ──


class TestSkewBuilder:
    """SkewBuilder: delta 坐标的 IV 偏斜曲线。"""

    def test_x_axis_is_delta(self, mock_monies: MoniesFrame):
        """X 轴应为 delta 0~100。"""
        sk = SkewBuilder.build(mock_monies, expiry="2026-04-18")
        assert "delta" in sk.df.columns
        assert sk.df["delta"].min() == 0
        assert sk.df["delta"].max() == 100

    def test_21_delta_points(self, mock_monies: MoniesFrame):
        """单到期日应产生 21 个 delta 采样点 (步长 5)。"""
        sk = SkewBuilder.build(mock_monies, expiry="2026-04-18")
        assert len(sk.df) == 21

    def test_delta_step_is_5(self, mock_monies: MoniesFrame):
        """delta 步长应为 5。"""
        sk = SkewBuilder.build(mock_monies, expiry="2026-04-18")
        deltas = sorted(sk.df["delta"].unique())
        assert deltas == list(range(0, 101, 5))

    def test_select_by_dte(self, mock_monies: MoniesFrame):
        """dte 参数应选择最接近的到期日。"""
        sk = SkewBuilder.build(mock_monies, dte=50)  # closest to 45
        assert set(sk.df["expirDate"]) == {"2026-05-16"}

    def test_compare_multiple_expiries(self, mock_monies: MoniesFrame):
        """compare 应叠加多个到期日。"""
        sk = SkewBuilder.build(
            mock_monies, expiry="2026-04-18", compare=["2026-06-19"]
        )
        assert len(sk.df) == 42  # 21 × 2
        assert set(sk.df["expirDate"]) == {"2026-04-18", "2026-06-19"}

    def test_default_selects_nearest(self, mock_monies: MoniesFrame):
        """不指定 expiry/dte 时默认取最近到期日。"""
        sk = SkewBuilder.build(mock_monies)
        assert set(sk.df["expirDate"]) == {"2026-04-18"}  # dte=17 最小

    def test_output_is_skewframe(self, mock_monies: MoniesFrame):
        sk = SkewBuilder.build(mock_monies, expiry="2026-04-18")
        assert isinstance(sk, SkewFrame)


# ── SmileBuilder Tests ──


class TestSmileBuilder:
    """SmileBuilder: strike 坐标的 IV 微笑曲线。"""

    def test_x_axis_is_strike(self, mock_strikes: StrikesFrame):
        """X 轴应为 strike price。"""
        sm = SmileBuilder.build(mock_strikes, expiry="2026-04-18")
        assert "strike" in sm.df.columns
        assert set(sm.df["strike"]) == {210, 215, 220}

    def test_sorted_by_strike(self, mock_strikes: StrikesFrame):
        """输出应按 strike 升序排列。"""
        sm = SmileBuilder.build(mock_strikes, expiry="2026-04-18")
        assert sm.df["strike"].is_monotonic_increasing

    def test_all_filter_has_both_iv(self, mock_strikes: StrikesFrame):
        """contract_filter='all' 应包含 call_iv 和 put_iv。"""
        sm = SmileBuilder.build(mock_strikes, expiry="2026-04-18", contract_filter="all")
        assert "call_iv" in sm.df.columns
        assert "put_iv" in sm.df.columns

    def test_calls_filter_no_put_iv(self, mock_strikes: StrikesFrame):
        """contract_filter='calls' 不应包含 put_iv。"""
        sm = SmileBuilder.build(mock_strikes, expiry="2026-04-18", contract_filter="calls")
        assert "call_iv" in sm.df.columns
        assert "put_iv" not in sm.df.columns

    def test_puts_filter_no_call_iv(self, mock_strikes: StrikesFrame):
        """contract_filter='puts' 不应包含 call_iv。"""
        sm = SmileBuilder.build(mock_strikes, expiry="2026-04-18", contract_filter="puts")
        assert "put_iv" in sm.df.columns
        assert "call_iv" not in sm.df.columns

    def test_overlay_smv_default_on(self, mock_strikes: StrikesFrame):
        """默认 overlay_smv=True 应包含 smv_vol 列。"""
        sm = SmileBuilder.build(mock_strikes, expiry="2026-04-18")
        assert "smv_vol" in sm.df.columns

    def test_overlay_smv_off(self, mock_strikes: StrikesFrame):
        """overlay_smv=False 不应包含 smv_vol 列。"""
        sm = SmileBuilder.build(mock_strikes, expiry="2026-04-18", overlay_smv=False)
        assert "smv_vol" not in sm.df.columns

    def test_filters_by_expiry(self, mock_strikes: StrikesFrame):
        """应只包含指定到期日的数据。"""
        sm = SmileBuilder.build(mock_strikes, expiry="2026-05-16")
        assert len(sm.df) == 3  # 3 strikes for May expiry

    def test_output_is_smileframe(self, mock_strikes: StrikesFrame):
        sm = SmileBuilder.build(mock_strikes, expiry="2026-04-18")
        assert isinstance(sm, SmileFrame)
