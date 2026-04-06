"""
compute/volatility/skew.py — SkewBuilder: 2D IV 偏斜曲线 (delta 坐标)

职责: 从 MoniesFrame 构建 IV skew 曲线。
      Skew 使用 delta 作为 X 轴（标准化坐标），便于跨标的/跨时间比较。
      与 Smile（X=strike）的区别: skew 消除了标的价格和到期日的影响。

依赖: compute.volatility.models (SkewFrame),
      provider.models (MoniesFrame)
被依赖: commands/ 层调用 SkewBuilder.build()
"""

from __future__ import annotations

import pandas as pd

from provider.models import MoniesFrame
from .models import SkewFrame


class SkewBuilder:
    """2D IV 偏斜曲线构建器。

    从 MoniesFrame 的 vol0~vol100 提取指定到期日的 delta 切片。
    支持 compare 模式叠加多个到期日，用于观察 skew 随时间的变化。
    """

    @staticmethod
    def build(
        monies_frame: MoniesFrame,
        expiry: str | None = None,
        dte: int | None = None,
        compare: list[str] | None = None,
    ) -> SkewFrame:
        """构建 IV skew 曲线。

        通过 expiry 或 dte 指定目标到期日。
        compare 可叠加多个到期日进行比较。

        Args:
            monies_frame: 按到期日分组的 SMV 数据
            expiry: 目标到期日 "YYYY-MM-DD"
            dte: 目标 DTE（取最近匹配的到期日）
            compare: 额外叠加的到期日列表

        Returns:
            SkewFrame: 包含 delta, iv, expirDate 的 skew 数据
        """
        df = monies_frame.df

        # 确定要提取的到期日集合
        target_rows = _select_expiries(df, expiry, dte, compare)

        # vol0~vol100 列 → delta 0~100（步长 5）
        vol_cols = [f"vol{i}" for i in range(0, 101, 5)]
        delta_values = list(range(0, 101, 5))

        rows = []
        for _, row in target_rows.iterrows():
            expir = row.get("expirDate", "unknown")
            for col, delta in zip(vol_cols, delta_values):
                if col in target_rows.columns:
                    rows.append({
                        "delta": delta,
                        "iv": row[col],
                        "expirDate": expir,
                    })

        return SkewFrame(df=pd.DataFrame(rows))


def _select_expiries(
    df: pd.DataFrame,
    expiry: str | None,
    dte: int | None,
    compare: list[str] | None,
) -> pd.DataFrame:
    """筛选目标到期日行。

    优先级: expiry > dte > 默认取最近到期日。
    compare 列表中的到期日也会被包含。

    Args:
        df: MoniesFrame 的底层 DataFrame
        expiry: 精确到期日
        dte: 目标 DTE
        compare: 额外到期日列表

    Returns:
        DataFrame: 筛选后的行
    """
    masks = []

    if expiry is not None and "expirDate" in df.columns:
        masks.append(df["expirDate"] == expiry)
    elif dte is not None and "dte" in df.columns:
        # 取最接近目标 DTE 的到期日
        closest_idx = (df["dte"] - dte).abs().idxmin()
        masks.append(df.index == closest_idx)
    else:
        # 默认: 取最近（最小 DTE）到期日
        if "dte" in df.columns and not df.empty:
            min_dte = df["dte"].min()
            masks.append(df["dte"] == min_dte)

    # 叠加 compare 到期日
    if compare and "expirDate" in df.columns:
        for exp in compare:
            masks.append(df["expirDate"] == exp)

    if not masks:
        return df

    # 合并所有 mask (OR)
    combined = masks[0]
    for m in masks[1:]:
        combined = combined | m

    return df[combined]
