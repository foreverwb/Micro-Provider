"""
compute/earnings/iv_rank.py — IV Rank 与 IV Percentile 计算

职责: 从当前 IV 和历史 IV 序列精确计算 IVR 和 IVP。

依赖: 无内部依赖
被依赖: commands/ 层 ivrank 命令

IVR 与 IVP 的区别:
- IVR (IV Rank): (当前IV - 52wk低) / (52wk高 - 52wk低)
  线性位置，对单次 spike 极度敏感——一次 spike 到 80% 会压低
  后续所有 IVR 读数（因为 high 被拉高了）。
- IVP (IV Percentile): 过去 N 日中低于当前 IV 的百分比
  概率位置，对 spike 不敏感——一次 spike 只影响 1 个数据点。

系统同时计算两者，用于 regime 模块的交叉验证。
"""

from __future__ import annotations

import pandas as pd


def compute_iv_rank(
    current_iv: float,
    hist_iv_series: pd.Series,
    period: int = 252,
) -> tuple[float, float]:
    """计算 IV Rank 和 IV Percentile。

    Args:
        current_iv: 当前 ATM IV（小数形式，如 0.25）
        hist_iv_series: 历史 ATM IV 时间序列（按日期排序）。
                        至少需要 period 个数据点以获得有意义的结果。
        period: 回溯期（交易日数），默认 252（≈1 年）

    Returns:
        tuple: (iv_rank, iv_percentile)，均为 0~100 的百分数
            - iv_rank: 当前 IV 在 period 内极值区间的线性位置
            - iv_percentile: period 内低于当前 IV 的交易日占比
    """
    # 取最近 period 个数据点
    recent = hist_iv_series.tail(period)

    if recent.empty:
        return 0.0, 0.0

    iv_high = recent.max()
    iv_low = recent.min()

    # IVR = (current - low) / (high - low) × 100
    # 如果 high == low（极端情况: 所有历史 IV 相同），IVR = 0
    if iv_high == iv_low:
        iv_rank = 0.0
    else:
        iv_rank = ((current_iv - iv_low) / (iv_high - iv_low)) * 100

    # IVP = 低于 current_iv 的历史数据点占比 × 100
    below_count = (recent < current_iv).sum()
    iv_percentile = (below_count / len(recent)) * 100

    # Clamp to 0~100 (current_iv 可能超出历史范围)
    iv_rank = max(0.0, min(100.0, iv_rank))
    iv_percentile = max(0.0, min(100.0, iv_percentile))

    return iv_rank, iv_percentile
