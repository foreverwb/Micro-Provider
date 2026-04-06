"""
compute/earnings/implied_move.py — 隐含波动幅度计算

职责: 从 ATM straddle 价格估算市场隐含的财报波动幅度。

依赖: 无内部依赖（使用 pandas DataFrame）
被依赖: commands/ 层 ermv 命令

公式: implied_move ≈ ATM_straddle_price / spot_price × 100%
其中 ATM straddle = ATM call mid + ATM put mid

这是市场对下一个重大事件（通常是财报）导致的价格变动的定价。
如果 implied_move = 5%，市场预期标的在财报后 ±5% 波动。
"""

from __future__ import annotations

import pandas as pd


def compute_implied_move(
    strikes_df: pd.DataFrame,
    spot_price: float,
) -> float:
    """计算隐含波动幅度（百分比）。

    找到最接近 ATM 的 strike，取其 straddle 价格估算 implied move。

    公式: implied_move = (ATM_call_mid + ATM_put_mid) / spot × 100

    ATM 的选取: 取 |strike - spot| 最小的行。
    如果数据包含多个到期日，应预先筛选为最近财报相关到期日。

    Args:
        strikes_df: 包含 strike, callValue (或 callBidPrice/callAskPrice),
                    putValue (或 putBidPrice/putAskPrice) 列的 DataFrame。
                    应为单一到期日的数据。
        spot_price: 当前现货价格

    Returns:
        float: 隐含波动幅度百分比（如 5.2 表示 ±5.2%）
    """
    df = strikes_df.copy()

    # 找到最接近 ATM 的 strike
    df["_atm_dist"] = (df["strike"] - spot_price).abs()
    atm_row = df.loc[df["_atm_dist"].idxmin()]

    # 取 call 和 put 的中间价
    # 优先使用 callValue/putValue（Provider 提供的理论中间价）
    # 否则用 (bid + ask) / 2
    call_mid = _get_mid_price(atm_row, "call")
    put_mid = _get_mid_price(atm_row, "put")

    # Straddle price = call + put
    straddle = call_mid + put_mid

    # Implied move = straddle / spot × 100%
    implied_move_pct = (straddle / spot_price) * 100

    return implied_move_pct


def _get_mid_price(row: pd.Series, side: str) -> float:
    """提取 call 或 put 的中间价。

    优先使用 {side}Value，否则使用 (bid + ask) / 2。

    Args:
        row: DataFrame 单行
        side: "call" 或 "put"

    Returns:
        float: 中间价
    """
    # 优先: Provider 理论中间价
    value_col = f"{side}Value"
    if value_col in row.index and pd.notna(row[value_col]):
        return float(row[value_col])

    # 备选: (bid + ask) / 2
    bid_col = f"{side}BidPrice"
    ask_col = f"{side}AskPrice"
    if bid_col in row.index and ask_col in row.index:
        bid = row[bid_col]
        ask = row[ask_col]
        if pd.notna(bid) and pd.notna(ask):
            return (float(bid) + float(ask)) / 2

    return 0.0
