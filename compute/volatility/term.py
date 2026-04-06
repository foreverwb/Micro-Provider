"""
compute/volatility/term.py — TermBuilder: 1D 期限结构

职责: 构建 ATM IV 期限结构曲线。
      期限结构展示 ATM IV 随到期日（DTE）的变化趋势:
      - 正常市场: 远月 IV > 近月 IV（contango / 升水）
      - 压力市场: 近月 IV > 远月 IV（backwardation / 倒挂）
      期限结构形态是 regime 分类的重要参考信号。

依赖: compute.volatility.models (TermFrame),
      provider.models (MoniesFrame, SummaryRecord)
被依赖: commands/ 层调用 TermBuilder.build()
"""

from __future__ import annotations

import pandas as pd

from provider.models import MoniesFrame, SummaryRecord
from .models import TermFrame


class TermBuilder:
    """1D 期限结构构建器。

    默认从 MoniesFrame 的 per-expiry atmiv 构建。
    可选叠加 SummaryRecord 的 atmFcstIvM1~M4 预测值，
    用于观察当前 IV 与市场预测的偏离。
    """

    @staticmethod
    def build(
        monies_frame: MoniesFrame,
        summary_record: SummaryRecord | None = None,
        overlay: bool = False,
    ) -> TermFrame:
        """构建期限结构。

        Args:
            monies_frame: 按到期日分组的 SMV 数据
            summary_record: 标的汇总数据（包含 M1~M4 预测 IV）。
                            overlay=True 时必须提供。
            overlay: 是否叠加 forecast IV 预测线

        Returns:
            TermFrame: 包含 dte, atmiv, (可选 expirDate, forecast_iv) 的结构
        """
        df = monies_frame.df.copy()

        # 从 MoniesFrame 提取 per-expiry 的 ATM IV
        cols = ["atmiv"]
        if "dte" in df.columns:
            cols.insert(0, "dte")
        if "expirDate" in df.columns:
            cols.append("expirDate")

        term_df = df[cols].copy()

        # 按 DTE 排序，近月在前
        if "dte" in term_df.columns:
            term_df = term_df.sort_values("dte").reset_index(drop=True)

        # 叠加 SummaryRecord 的 forecast IV (M1~M4)
        if overlay and summary_record is not None:
            term_df = _overlay_forecast(term_df, summary_record)

        return TermFrame(df=term_df)


def _overlay_forecast(
    term_df: pd.DataFrame,
    summary: SummaryRecord,
) -> pd.DataFrame:
    """将 SummaryRecord 的 atmFcstIvM1~M4 叠加到期限结构上。

    M1~M4 对应前 4 个最近到期月的 ATM IV 预测值。
    通过 dtExM1~M4（DTE）对齐到 term_df 的行。

    Args:
        term_df: 已有的期限结构 DataFrame
        summary: 包含 forecast 数据的 SummaryRecord

    Returns:
        DataFrame: 增加了 forecast_iv 列的 term_df
    """
    # 构建 forecast 映射: DTE → forecast IV
    forecast_map: dict[int, float] = {}
    for i in range(1, 5):
        dte = getattr(summary, f"dtExM{i}", None)
        fcst = getattr(summary, f"atmFcstIvM{i}", None)
        if dte is not None and fcst is not None:
            forecast_map[dte] = fcst

    if forecast_map and "dte" in term_df.columns:
        # 将 forecast 值按 DTE 匹配到 term_df
        term_df["forecast_iv"] = term_df["dte"].map(forecast_map)

    return term_df
