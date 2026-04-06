"""
tests/test_earnings.py — 财报事件分析模块测试

测试覆盖:
- implied_move: ATM straddle 百分比计算 + bid/ask fallback
- iv_rank: IVR 线性位置 + IVP 概率位置 + 边界情况
"""

import pandas as pd
import pytest

from compute.earnings.implied_move import compute_implied_move
from compute.earnings.iv_rank import compute_iv_rank


# ── Implied Move Tests ──


class TestImpliedMove:
    """compute_implied_move: straddle / spot × 100%。"""

    def test_basic_calculation(self):
        """callValue=8, putValue=7, spot=200 → (8+7)/200*100 = 7.5%。"""
        df = pd.DataFrame({
            "strike": [195, 200, 205],
            "callValue": [12.0, 8.0, 4.5],
            "putValue": [3.5, 7.0, 11.0],
        })
        im = compute_implied_move(df, spot_price=200)
        # ATM = strike=200: straddle = 8+7 = 15, 15/200*100 = 7.5%
        assert im == pytest.approx(7.5)

    def test_selects_closest_atm(self):
        """spot=198 时应选 strike=200 而非 195。"""
        df = pd.DataFrame({
            "strike": [195, 200, 205],
            "callValue": [12.0, 8.0, 4.5],
            "putValue": [3.5, 7.0, 11.0],
        })
        im = compute_implied_move(df, spot_price=198)
        # |198-195|=3, |198-200|=2 → 选 200
        # straddle = 8+7 = 15, 15/198*100 ≈ 7.576%
        assert im == pytest.approx(15.0 / 198 * 100, rel=1e-4)

    def test_bid_ask_fallback(self):
        """无 callValue/putValue 时用 (bid+ask)/2。"""
        df = pd.DataFrame({
            "strike": [100],
            "callBidPrice": [4.80], "callAskPrice": [5.20],
            "putBidPrice": [4.50], "putAskPrice": [4.90],
        })
        im = compute_implied_move(df, spot_price=100)
        # call_mid = (4.80+5.20)/2 = 5.0
        # put_mid  = (4.50+4.90)/2 = 4.7
        # straddle = 9.7, 9.7/100*100 = 9.7%
        assert im == pytest.approx(9.7)

    def test_prefers_value_over_bid_ask(self):
        """callValue/putValue 优先于 bid/ask。"""
        df = pd.DataFrame({
            "strike": [100],
            "callValue": [5.0], "putValue": [4.7],
            "callBidPrice": [99.0], "callAskPrice": [99.0],
            "putBidPrice": [99.0], "putAskPrice": [99.0],
        })
        im = compute_implied_move(df, spot_price=100)
        # 应用 callValue=5+putValue=4.7=9.7, 非 bid/ask
        assert im == pytest.approx(9.7)

    def test_single_strike(self):
        """单行数据也能正常工作。"""
        df = pd.DataFrame({
            "strike": [150],
            "callValue": [6.0], "putValue": [5.5],
        })
        im = compute_implied_move(df, spot_price=150)
        assert im == pytest.approx(11.5 / 150 * 100)


# ── IV Rank Tests ──


class TestIVRank:
    """compute_iv_rank: IVR 线性位置 + IVP 概率位置。"""

    def test_basic_example(self):
        """历史 [10,15,20,25,30], 当前=22:
        IVR = (22-10)/(30-10)*100 = 60%
        IVP = 3/5*100 = 60% (10,15,20 都 < 22)
        """
        hist = pd.Series([10, 15, 20, 25, 30])
        ivr, ivp = compute_iv_rank(22, hist, period=5)
        assert ivr == pytest.approx(60.0)
        assert ivp == pytest.approx(60.0)

    def test_at_minimum(self):
        """当前=历史最低值: IVR=0, IVP=0。"""
        hist = pd.Series([10, 15, 20, 25, 30])
        ivr, ivp = compute_iv_rank(10, hist, period=5)
        assert ivr == pytest.approx(0.0)
        assert ivp == pytest.approx(0.0)

    def test_at_maximum(self):
        """当前=历史最高值: IVR=100, IVP=80% (4/5 below)。"""
        hist = pd.Series([10, 15, 20, 25, 30])
        ivr, ivp = compute_iv_rank(30, hist, period=5)
        assert ivr == pytest.approx(100.0)
        assert ivp == pytest.approx(80.0)  # 4 out of 5 are below 30

    def test_above_range_clamped(self):
        """当前超出历史最高: IVR 和 IVP 都 clamp 到 100。"""
        hist = pd.Series([10, 15, 20, 25, 30])
        ivr, ivp = compute_iv_rank(50, hist, period=5)
        assert ivr == 100.0
        assert ivp == 100.0

    def test_below_range_clamped(self):
        """当前低于历史最低: IVR clamp 到 0, IVP = 0。"""
        hist = pd.Series([10, 15, 20, 25, 30])
        ivr, ivp = compute_iv_rank(5, hist, period=5)
        assert ivr == 0.0
        assert ivp == 0.0

    def test_flat_history(self):
        """所有历史 IV 相同: high==low → IVR=0。"""
        hist = pd.Series([0.20] * 100)
        ivr, ivp = compute_iv_rank(0.20, hist, period=100)
        assert ivr == 0.0
        assert ivp == 0.0

    def test_period_truncation(self):
        """period 应只使用最近 N 个数据点。"""
        # 前 100 天: IV=0.10~0.15, 后 50 天: IV=0.20~0.30
        early = pd.Series([0.10 + 0.05 * i / 99 for i in range(100)])
        late = pd.Series([0.20 + 0.10 * i / 49 for i in range(50)])
        hist = pd.concat([early, late], ignore_index=True)

        # period=50: 只看最近 50 天 (0.20~0.30)
        ivr, ivp = compute_iv_rank(0.25, hist, period=50)
        # high=0.30, low=0.20, IVR = (0.25-0.20)/(0.30-0.20)*100 = 50%
        assert ivr == pytest.approx(50.0, abs=1.0)

    def test_empty_history(self):
        """空历史序列返回 (0, 0)。"""
        hist = pd.Series([], dtype=float)
        ivr, ivp = compute_iv_rank(0.25, hist)
        assert ivr == 0.0
        assert ivp == 0.0

    def test_ivr_vs_ivp_divergence(self):
        """IVR 对 spike 敏感，IVP 不敏感。

        历史: 99 天 IV=0.20, 1 天 spike 到 0.80
        当前 IV=0.25
        IVR = (0.25-0.20)/(0.80-0.20)*100 = 8.3% (被 spike 压低)
        IVP = 1/100*100 = 1% (只有 spike 那天高于 0.25... 不对)
        IVP = count(< 0.25)/100: 99 天的 0.20 都 < 0.25, spike=0.80 不 < 0.25
              = 99/100*100 = 99%
        这就是 IVR vs IVP 分歧的典型场景。
        """
        hist = pd.Series([0.20] * 99 + [0.80])
        ivr, ivp = compute_iv_rank(0.25, hist, period=100)
        # IVR: spike 拉高 high，压低 rank
        assert ivr == pytest.approx((0.25 - 0.20) / (0.80 - 0.20) * 100, abs=0.1)
        assert ivr < 10  # 只有 ~8.3%
        # IVP: spike 只影响 1 个数据点
        assert ivp == pytest.approx(99.0)  # 99/100
        # 分歧度 > 80
        assert abs(ivr - ivp) > 80
