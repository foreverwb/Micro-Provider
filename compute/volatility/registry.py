"""
compute/volatility/registry.py — MetricDef + MetricRegistry 全局注册表

职责: 集中注册所有 surface/skew/smile/term 支持的 metric，
      驱动策略路由。新增 metric 只需在 METRIC_REGISTRY 字典中添加一行，
      无需修改 Strategy 类——开闭原则的实践。

依赖: compute.exposure.scaling (缩放函数常量)
被依赖: compute.volatility.surface, skew, smile, term (lookup metric 定义)

设计参考: 设计文档 §6.3.1
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..exposure.scaling import (
    DELTA_EXPOSURE,
    GAMMA_EXPOSURE,
    RAW,
    VEGA_EXPOSURE,
    ScalingFn,
)


class DataSource(Enum):
    """Metric 数据来源。

    MONIES: 来自 /monies/implied 端点，IV 域 metric
    STRIKES: 来自 /strikes 端点，Greeks/Exposure 域 metric
    """

    MONIES = "monies"
    STRIKES = "strikes"


class StrategyType(Enum):
    """Surface 构建策略类型。

    IV_SURFACE: 从 MoniesFrame 的 vol0~vol100 构建，X=delta
    GREEK_SURFACE: 从 StrikesFrame 构建，X=strike
    """

    IV_SURFACE = "iv_surface"
    GREEK_SURFACE = "greek_surface"


@dataclass(frozen=True)
class MetricDef:
    """Metric 定义。

    Attributes:
        source: 数据来源 (MONIES 或 STRIKES)
        strategy: 构建策略类型
        z_label: Z 轴标签（用于图表展示）
        scaling: 缩放函数（仅 Greeks/Exposure 域使用）
        requires_oi: 是否需要 OI 数据（Exposure 域 = True）
    """

    source: DataSource
    strategy: StrategyType
    z_label: str
    scaling: ScalingFn = RAW
    requires_oi: bool = False


class UnknownMetricError(KeyError):
    """未注册的 metric 名称。"""

    def __init__(self, metric: str) -> None:
        self.metric = metric
        available = ", ".join(sorted(METRIC_REGISTRY.keys()))
        super().__init__(
            f"Unknown metric '{metric}'. Available: {available}"
        )


# ── 全局注册表 ──
# 新增 metric 只需在此添加一行，无需修改任何 Strategy 类

METRIC_REGISTRY: dict[str, MetricDef] = {
    # ── IV Domain ──
    # 数据源: MoniesFrame (vol0~vol100)，X 轴 = delta (0~100)
    "iv": MetricDef(
        source=DataSource.MONIES,
        strategy=StrategyType.IV_SURFACE,
        z_label="IV %",
    ),
    "smvVol": MetricDef(
        source=DataSource.MONIES,
        strategy=StrategyType.IV_SURFACE,
        z_label="SMV Vol %",
    ),
    "ivask": MetricDef(
        source=DataSource.MONIES,
        strategy=StrategyType.IV_SURFACE,
        z_label="Ask IV %",
    ),
    "calVol": MetricDef(
        source=DataSource.MONIES,
        strategy=StrategyType.IV_SURFACE,
        z_label="Calendar Vol",
    ),
    "earnEffect": MetricDef(
        source=DataSource.MONIES,
        strategy=StrategyType.IV_SURFACE,
        z_label="Earn Effect",
    ),
    # ── Greeks Domain ──
    # 数据源: StrikesFrame，X 轴 = strike price，原始 Greek 值
    "gamma": MetricDef(
        source=DataSource.STRIKES,
        strategy=StrategyType.GREEK_SURFACE,
        z_label="Gamma",
        scaling=RAW,
    ),
    "delta": MetricDef(
        source=DataSource.STRIKES,
        strategy=StrategyType.GREEK_SURFACE,
        z_label="Delta",
        scaling=RAW,
    ),
    "vega": MetricDef(
        source=DataSource.STRIKES,
        strategy=StrategyType.GREEK_SURFACE,
        z_label="Vega",
        scaling=RAW,
    ),
    "theta": MetricDef(
        source=DataSource.STRIKES,
        strategy=StrategyType.GREEK_SURFACE,
        z_label="Theta",
        scaling=RAW,
    ),
    # ── Exposure Domain (Greeks × OI) ──
    # 数据源: StrikesFrame，X 轴 = strike price，需要 OI 参与计算
    "gex": MetricDef(
        source=DataSource.STRIKES,
        strategy=StrategyType.GREEK_SURFACE,
        z_label="GEX $",
        scaling=GAMMA_EXPOSURE,
        requires_oi=True,
    ),
    "dex": MetricDef(
        source=DataSource.STRIKES,
        strategy=StrategyType.GREEK_SURFACE,
        z_label="DEX $",
        scaling=DELTA_EXPOSURE,
        requires_oi=True,
    ),
    "vex": MetricDef(
        source=DataSource.STRIKES,
        strategy=StrategyType.GREEK_SURFACE,
        z_label="VEX $",
        scaling=VEGA_EXPOSURE,
        requires_oi=True,
    ),
}


def lookup(metric: str) -> MetricDef:
    """查找 metric 定义。

    Args:
        metric: metric 名称（如 "iv", "gex", "gamma"）

    Returns:
        MetricDef: metric 的完整定义

    Raises:
        UnknownMetricError: metric 未在注册表中
    """
    if metric not in METRIC_REGISTRY:
        raise UnknownMetricError(metric)
    return METRIC_REGISTRY[metric]
