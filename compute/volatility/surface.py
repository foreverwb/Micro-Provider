"""
compute/volatility/surface.py — SurfaceBuilder + 策略实现

职责: 统一入口构建二维波动率/Greeks 曲面。
      通过 MetricRegistry 路由到 IVSurfaceStrategy 或 GreekSurfaceStrategy。

依赖: compute.volatility.registry (MetricDef, lookup),
      compute.volatility.models (SurfaceFrame, CoordType),
      compute.exposure.calculator (compute_exposure — GreekSurfaceStrategy 需要),
      provider.models (StrikesFrame, MoniesFrame)
被依赖: commands/ 层调用 SurfaceBuilder.build()
"""

from __future__ import annotations

from typing import Union

import pandas as pd

from provider.models import MoniesFrame, StrikesFrame
from ..exposure.calculator import compute_exposure
from ..exposure.models import SignConvention
from .models import CoordType, SurfaceFrame
from .registry import DataSource, MetricDef, StrategyType, lookup


class SurfaceBuilder:
    """二维曲面统一构建入口。

    通过 MetricRegistry 路由:
    - IV 域 metric → IVSurfaceStrategy (数据源: MoniesFrame)
    - Greeks 域 metric → GreekSurfaceStrategy (数据源: StrikesFrame)
    """

    @staticmethod
    def build(
        metric: str,
        data: Union[MoniesFrame, StrikesFrame],
    ) -> SurfaceFrame:
        """构建二维曲面。

        Args:
            metric: metric 名称（如 "iv", "gex", "gamma"）
            data: MoniesFrame (IV 域) 或 StrikesFrame (Greeks 域)

        Returns:
            SurfaceFrame: 二维曲面数据

        Raises:
            UnknownMetricError: metric 未注册
            TypeError: data 类型与 metric 的 source 不匹配
        """
        metric_def = lookup(metric)

        if metric_def.strategy == StrategyType.IV_SURFACE:
            if not isinstance(data, MoniesFrame):
                raise TypeError(
                    f"Metric '{metric}' requires MoniesFrame, "
                    f"got {type(data).__name__}"
                )
            return _build_iv_surface(metric_def, data)

        # GreekSurfaceStrategy
        if not isinstance(data, StrikesFrame):
            raise TypeError(
                f"Metric '{metric}' requires StrikesFrame, "
                f"got {type(data).__name__}"
            )
        return _build_greek_surface(metric, metric_def, data)


def _build_iv_surface(
    metric_def: MetricDef,
    monies: MoniesFrame,
) -> SurfaceFrame:
    """从 MoniesFrame 构建 IV 域曲面。

    X 轴 = delta (0~100, 步长 5，共 21 个采样点)
    Y 轴 = DTE
    Z 值 = vol0~vol100 中对应列的值

    MoniesFrame 每行是一个到期日的完整 SMV 曲线，
    vol0~vol100 是不同 delta 水平的隐含波动率。
    """
    df = monies.df.copy()

    # 提取 vol0~vol100 列名（步长 5）
    vol_cols = [f"vol{i}" for i in range(0, 101, 5)]
    # delta 对应值: 0, 5, 10, ..., 100
    delta_values = list(range(0, 101, 5))

    # 构建 pivot: 行=到期日(dte), 列=delta
    rows = []
    for _, row in df.iterrows():
        dte = row.get("dte", row.get("expirDate", None))
        for col, delta in zip(vol_cols, delta_values):
            if col in df.columns:
                rows.append({"dte": dte, "delta": delta, "value": row[col]})

    pivot_df = pd.DataFrame(rows)
    # pivot: 行=dte, 列=delta, 值=IV
    surface_data = pivot_df.pivot(index="dte", columns="delta", values="value")

    return SurfaceFrame(
        x_axis="delta",
        z_label=metric_def.z_label,
        data=surface_data,
        coord_type=CoordType.DELTA,
    )


def _build_greek_surface(
    metric: str,
    metric_def: MetricDef,
    strikes: StrikesFrame,
) -> SurfaceFrame:
    """从 StrikesFrame 构建 Greeks/Exposure 域曲面。

    X 轴 = strike price
    Y 轴 = DTE
    Z 值 = Greek 原值 或 Exposure 值（经 scaling + OI 计算）

    若 requires_oi=True（Exposure 域），调用 compute_exposure() 计算暴露值。
    否则（Greeks 域），直接使用原始 Greek 列。
    """
    if metric_def.requires_oi:
        # Exposure 域: 需要通过 compute_exposure 计算
        # 根据 metric 名确定 greek 和 sign_convention
        greek_map = {"gex": "gamma", "dex": "delta", "vex": "vega"}
        greek = greek_map.get(metric, metric)

        # GEX put 侧取反，DEX/VEX 保持原始符号
        sign = (
            SignConvention.NEGATE_PUT
            if metric == "gex"
            else SignConvention.KEEP_SIGN
        )

        exposure = compute_exposure(
            strikes, greek=greek,
            scaling_fn=metric_def.scaling, sign_convention=sign,
        )
        df = exposure.df.copy()
        value_col = "exposure_value"
    else:
        # Greeks 域: 直接使用原始 Greek 列
        df = strikes.df.copy()
        value_col = metric

    # pivot: 行=dte, 列=strike, 值=Z
    surface_data = df.pivot_table(
        index="dte", columns="strike", values=value_col, aggfunc="mean",
    )

    return SurfaceFrame(
        x_axis="strike",
        z_label=metric_def.z_label,
        data=surface_data,
        coord_type=CoordType.STRIKE,
    )
