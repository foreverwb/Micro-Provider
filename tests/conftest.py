"""
tests/conftest.py — 共享 mock fixtures

提供基于 AAPL 真实数据结构（造假数值）的 mock fixtures，
以及不发 HTTP 请求的 mock_orats_provider。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from provider.models import (
    HistSummaryFrame,
    IVRankRecord,
    MoniesFrame,
    StrikesFrame,
    SummaryRecord,
)


# ──────────────────────────────────────────────
# 原始 DataFrame fixtures（AAPL mock 数据）
# ──────────────────────────────────────────────

SPOT = 218.50
TICKER = "AAPL"
EXPIRIES = ["2026-04-18", "2026-05-16", "2026-06-19"]
DTES = [17, 45, 90]
# 以 spot 为中心，±5 个 strike（步长 $2.50），共 10 个
STRIKES = [spot for spot in np.arange(SPOT - 12.5, SPOT + 12.5, 2.5)]


@pytest.fixture
def mock_strikes_df() -> pd.DataFrame:
    """3 个到期日 × 10 个 strike = 30 行，包含所有 exposure/surface 所需字段。"""
    rows = []
    for exp, dte in zip(EXPIRIES, DTES):
        for i, strike in enumerate(STRIKES):
            # delta 从 ITM (0.85) 到 OTM (0.15) 线性递减
            call_delta = 0.85 - i * 0.07
            gamma = 0.06 - abs(strike - SPOT) * 0.002
            gamma = max(gamma, 0.005)
            vega = 0.20 - abs(strike - SPOT) * 0.01
            vega = max(vega, 0.03)
            rows.append({
                "tradeDate": "2026-04-01",
                "expirDate": exp,
                "dte": dte,
                "strike": round(strike, 2),
                "spotPrice": SPOT,
                "gamma": round(gamma, 4),
                "delta": round(call_delta, 4),
                "vega": round(vega, 4),
                "theta": round(-0.05 - gamma * 10, 4),
                "callOpenInterest": 500 + i * 200,
                "putOpenInterest": 1500 - i * 100,
                "callVolume": 100 + i * 50,
                "putVolume": 200 - i * 10,
                "callMidIv": round(0.28 - call_delta * 0.05, 4),
                "putMidIv": round(0.30 - call_delta * 0.04, 4),
                "smvVol": round(0.27 - call_delta * 0.03, 4),
                "callValue": round(max(0, SPOT - strike) + 3.0 + gamma * 100, 2),
                "putValue": round(max(0, strike - SPOT) + 2.8 + gamma * 100, 2),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def mock_monies_df() -> pd.DataFrame:
    """5 个到期日，每行包含 vol0~vol100 + atmiv + slope + deriv。"""
    expiries = [
        ("2026-04-11", 10), ("2026-04-18", 17), ("2026-05-16", 45),
        ("2026-06-19", 90), ("2026-09-18", 171),
    ]
    rows = []
    for exp, dte in expiries:
        row: dict = {
            "ticker": TICKER,
            "tradeDate": "2026-04-01",
            "expirDate": exp,
            "dte": dte,
            "stockPrice": SPOT,
            "spotPrice": SPOT,
            "atmiv": round(0.22 + dte * 0.0005, 4),
            "slope": round(-0.12 + dte * 0.0003, 4),
            "deriv": round(0.015 - dte * 0.00005, 5),
        }
        # vol0~vol100: U 形 smile，ATM (vol50) 最低
        for d in range(0, 101, 5):
            dist_from_atm = abs(d - 50)
            row[f"vol{d}"] = round(row["atmiv"] + dist_from_atm * 0.001, 5)
        rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture
def mock_summary_data() -> dict:
    """单行 summaries 数据，覆盖 SummaryRecord 的关键字段。"""
    return {
        "ticker": TICKER,
        "tradeDate": "2026-04-01",
        "assetType": "equity",
        "priorCls": 217.80,
        "pxAtmIv": 0.235,
        "mktCap": 3_400_000_000_000,
        "cVolu": 450_000,
        "cOi": 3_200_000,
        "pVolu": 380_000,
        "pOi": 2_800_000,
        "orFcst20d": 0.19,
        "orIvFcst20d": 0.23,
        "orFcstInf": 0.21,
        "orIvXern20d": 0.22,
        "orIvXernInf": 0.20,
        "iv200Ma": 0.24,
        "atmIvM1": 0.225,
        "atmFitIvM1": 0.223,
        "atmFcstIvM1": 0.230,
        "dtExM1": 17,
        "atmIvM2": 0.240,
        "atmFitIvM2": 0.238,
        "atmFcstIvM2": 0.245,
        "dtExM2": 45,
        "atmIvM3": 0.260,
        "atmFitIvM3": 0.258,
        "atmFcstIvM3": 0.265,
        "dtExM3": 90,
        "atmIvM4": 0.275,
        "atmFitIvM4": 0.273,
        "atmFcstIvM4": 0.280,
        "dtExM4": 171,
        "iRate5wk": 0.052,
        "iRateLt": 0.045,
        "px1kGam": 1.25,
        "volOfVol": 0.055,
        "volOfIvol": 0.048,
        "slope": -0.105,
        "slopeInf": -0.095,
        "slopeFcst": -0.100,
        "slopeFcstInf": -0.090,
        "deriv": 0.013,
        "derivInf": 0.011,
        "derivFcst": 0.012,
        "derivFcstInf": 0.010,
        "mktWidthVol": 0.03,
        "mktWidthVolInf": 0.025,
        "ivEarnReturn": 0.04,
        "fcstR2": 0.85,
        "fcstR2Imp": 0.82,
        "stkVolu": 52_000_000,
        "avgOptVolu20d": 1_200_000,
        "spotPrice": SPOT,
    }


@pytest.fixture
def mock_ivrank_data() -> dict:
    """ivrank 端点返回数据。ivRank 和 ivPct 必须同时包含。"""
    return {
        "ticker": TICKER,
        "tradeDate": "2026-04-01",
        "ivRank": 48.0,     # 当前 IV 在 52 周区间的线性位置
        "ivPct": 52.0,      # 过去 N 日中低于当前 IV 的百分比
    }


# ──────────────────────────────────────────────
# 包装后的 Model fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def mock_strikes_frame(mock_strikes_df: pd.DataFrame) -> StrikesFrame:
    """StrikesFrame 包装。"""
    return StrikesFrame(df=mock_strikes_df)


@pytest.fixture
def mock_monies_frame(mock_monies_df: pd.DataFrame) -> MoniesFrame:
    """MoniesFrame 包装。"""
    return MoniesFrame(df=mock_monies_df)


@pytest.fixture
def mock_summary_record(mock_summary_data: dict) -> SummaryRecord:
    """SummaryRecord 包装。"""
    return SummaryRecord(**mock_summary_data)


@pytest.fixture
def mock_ivrank_record(mock_ivrank_data: dict) -> IVRankRecord:
    """IVRankRecord 包装。"""
    return IVRankRecord(
        iv_rank=mock_ivrank_data["ivRank"],
        iv_pctl=mock_ivrank_data["ivPct"],
    )


# ──────────────────────────────────────────────
# Mock OratsProvider（不发真实 HTTP 请求）
# ──────────────────────────────────────────────


@pytest.fixture
def mock_orats_provider(
    mock_strikes_frame: StrikesFrame,
    mock_monies_frame: MoniesFrame,
    mock_summary_record: SummaryRecord,
    mock_ivrank_record: IVRankRecord,
):
    """返回预设数据的 mock provider，实现 DataProvider Protocol 的所有方法。"""
    provider = AsyncMock()

    provider.get_strikes = AsyncMock(return_value=mock_strikes_frame)
    provider.get_monies = AsyncMock(return_value=mock_monies_frame)
    provider.get_summary = AsyncMock(return_value=mock_summary_record)
    provider.get_ivrank = AsyncMock(return_value=mock_ivrank_record)

    # get_hist_summary: 返回 252 天的模拟历史数据
    hist_df = pd.DataFrame({
        "tradeDate": pd.date_range("2025-04-01", periods=252, freq="B")
                       .strftime("%Y-%m-%d")
                       .tolist(),
        "ticker": [TICKER] * 252,
        "atmIvM1": [0.20 + 0.10 * i / 251 for i in range(252)],
    })
    provider.get_hist_summary = AsyncMock(
        return_value=HistSummaryFrame(df=hist_df)
    )

    return provider
