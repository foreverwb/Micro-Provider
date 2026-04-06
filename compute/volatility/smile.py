"""
compute/volatility/smile.py — SmileBuilder: 2D IV 微笑曲线 (strike 坐标)

职责: 从 StrikesFrame 构建 IV smile 曲线。
      Smile 使用 strike 作为 X 轴，保留绝对价格信息。
      与 Skew（X=delta）的区别: smile 直观展示哪些 strike 的 IV 偏高/偏低，
      但无法直接跨标的比较。

依赖: compute.volatility.models (SmileFrame),
      provider.models (StrikesFrame)
被依赖: commands/ 层调用 SmileBuilder.build()
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from provider.models import StrikesFrame
from .models import SmileFrame


class SmileBuilder:
    """2D IV 微笑曲线构建器。

    从 StrikesFrame 的 callMidIv/putMidIv/smvVol 构建。
    支持叠加 SMV 拟合线（overlay_smv），用于观察市场 IV 与模型 IV 的偏离。
    """

    @staticmethod
    def build(
        strikes_frame: StrikesFrame,
        expiry: str,
        contract_filter: Literal["calls", "puts", "all"] = "all",
        overlay_smv: bool = True,
    ) -> SmileFrame:
        """构建 IV smile 曲线。

        Args:
            strikes_frame: 逐 strike 粒度的期权数据
            expiry: 目标到期日 "YYYY-MM-DD"
            contract_filter: 合约类型过滤 ("calls", "puts", "all")
            overlay_smv: 是否叠加 SMV 拟合线

        Returns:
            SmileFrame: 包含 strike, call_iv, put_iv, (可选 smv_vol) 的数据
        """
        df = strikes_frame.df

        # 筛选目标到期日
        if "expirDate" in df.columns:
            mask = df["expirDate"] == expiry
            filtered = df[mask].copy()
        else:
            filtered = df.copy()

        # 构建 smile DataFrame
        result = pd.DataFrame({"strike": filtered["strike"]})

        # 根据 contract_filter 决定包含哪些 IV 列
        if contract_filter in ("calls", "all"):
            if "callMidIv" in filtered.columns:
                result["call_iv"] = filtered["callMidIv"].values

        if contract_filter in ("puts", "all"):
            if "putMidIv" in filtered.columns:
                result["put_iv"] = filtered["putMidIv"].values

        # 叠加 SMV 拟合线: smvVol 是 Surface Model Volatility（理论平滑 IV），
        # 与市场实际 IV 的偏离可用于寻找错价机会
        if overlay_smv and "smvVol" in filtered.columns:
            result["smv_vol"] = filtered["smvVol"].values

        # 按 strike 排序
        result = result.sort_values("strike").reset_index(drop=True)

        return SmileFrame(df=result)
