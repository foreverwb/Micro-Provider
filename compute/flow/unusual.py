"""
compute/flow/unusual.py — 异常期权活动检测

职责: 从 StrikesFrame 中筛选符合异常阈值条件的期权合约。

依赖: 无内部依赖（使用 pandas DataFrame + Pydantic model）
被依赖: commands/ 层 unusual 命令

异常活动指标:
- 高成交量: 单合约成交量显著高于均值
- 高 Vol/OI 比: 当日成交量远超持仓量，暗示新建仓位
- 高 OI: 持仓量本身异常高
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel


class UnusualThresholds(BaseModel):
    """异常活动检测阈值。

    Attributes:
        min_volume: 最小成交量过滤（排除低流动性噪音）
        min_oi: 最小持仓量过滤
        vol_oi_ratio: Volume/OI 比率阈值。
                      > 1.0 表示当日成交量超过现有持仓——暗示新建仓位。
                      典型设置 2.0~5.0。
    """

    min_volume: int = 100
    min_oi: int = 500
    vol_oi_ratio: float = 3.0


def detect_unusual(
    strikes_df: pd.DataFrame,
    thresholds: UnusualThresholds | None = None,
) -> pd.DataFrame:
    """检测异常期权活动。

    逻辑: 筛选同时满足以下条件的行:
    1. callVolume 或 putVolume >= min_volume
    2. callOI 或 putOI >= min_oi
    3. volume / OI >= vol_oi_ratio（暗示新建仓位）

    Args:
        strikes_df: 包含成交量和 OI 列的 DataFrame
        thresholds: 检测阈值，None 时使用默认值

    Returns:
        DataFrame: 符合异常条件的行，按 vol/oi ratio 降序排列
    """
    if thresholds is None:
        thresholds = UnusualThresholds()

    df = strikes_df.copy()
    results = []

    # 检测 call 侧异常
    if "callVolume" in df.columns and "callOpenInterest" in df.columns:
        call_mask = (
            (df["callVolume"] >= thresholds.min_volume)
            & (df["callOpenInterest"] >= thresholds.min_oi)
        )
        calls = df[call_mask].copy()
        if not calls.empty:
            calls["vol_oi_ratio"] = (
                calls["callVolume"] / calls["callOpenInterest"]
            )
            calls["side"] = "call"
            calls["volume"] = calls["callVolume"]
            calls["oi"] = calls["callOpenInterest"]
            calls = calls[calls["vol_oi_ratio"] >= thresholds.vol_oi_ratio]
            results.append(calls)

    # 检测 put 侧异常
    if "putVolume" in df.columns and "putOpenInterest" in df.columns:
        put_mask = (
            (df["putVolume"] >= thresholds.min_volume)
            & (df["putOpenInterest"] >= thresholds.min_oi)
        )
        puts = df[put_mask].copy()
        if not puts.empty:
            puts["vol_oi_ratio"] = (
                puts["putVolume"] / puts["putOpenInterest"]
            )
            puts["side"] = "put"
            puts["volume"] = puts["putVolume"]
            puts["oi"] = puts["putOpenInterest"]
            puts = puts[puts["vol_oi_ratio"] >= thresholds.vol_oi_ratio]
            results.append(puts)

    if not results:
        return pd.DataFrame()

    combined = pd.concat(results, ignore_index=True)
    # 按 vol/oi ratio 降序——最异常的排在最前
    return combined.sort_values("vol_oi_ratio", ascending=False).reset_index(
        drop=True
    )
