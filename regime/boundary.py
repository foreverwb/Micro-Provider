"""
regime/boundary.py — 市场状态分类与自适应边界推导

职责: 根据 6 个 regime 指标综合判定市场状态 (LOW_VOL / NORMAL / STRESS)，
      并推导出 strike window、dte window、cache TTL 等参数边界。

依赖: 无内部依赖（纯计算模块）
被依赖: commands/ 层调用 classify() 和 compute_derived_boundaries()
        infra/cache.py 使用推导出的 cache_ttl

设计参考: 设计文档 §5
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import ceil, sqrt


class RegimeClass(Enum):
    """市场状态三级分类。"""

    LOW_VOL = "LOW_VOL"
    NORMAL = "NORMAL"
    STRESS = "STRESS"


@dataclass
class MarketRegime:
    """市场状态指标集合。

    包含 6 个 regime 指标:
    - iv30d, contango, vrp: 由外部调用方传入
    - iv_rank, iv_pctl:     从数据源 /ivrank 端点获取
    - vol_of_vol:           从数据源 /summaries 端点获取

    Attributes:
        iv30d: 30 天常数期限隐含波动率 (小数形式, 如 0.22 表示 22%)
        contango: 期限升水/倒挂幅度 (正=升水, 负=backwardation)
        vrp: 波动率风险溢价 (IV - RV)
        iv_rank: IV Rank (0~100), 当前IV在52周极值区间的线性位置
        iv_pctl: IV Percentile (0~100), 过去N日中低于当前IV的百分比
        vol_of_vol: 波动率的波动率 (如 0.05)
    """

    iv30d: float
    contango: float
    vrp: float
    iv_rank: float
    iv_pctl: float
    vol_of_vol: float

    @property
    def iv_consensus(self) -> float:
        """IVR 与 IVP 的加权共识值 (0~100)。

        IVP 权重 0.6 > IVR 权重 0.4:
        IVP 对分布尖峰更鲁棒——一次历史 IV spike 会严重压低后续
        所有 IVR 读数，但只影响 IVP 的 1 个数据点。
        加权共识比单一指标更稳定可靠。
        """
        return 0.4 * self.iv_rank + 0.6 * self.iv_pctl

    @property
    def iv_divergence(self) -> float:
        """IVR 与 IVP 的分歧度 (0~100)。

        高分歧意味着 IV 分布存在偏态或历史 spike:
        - 分歧 > 30: IV 分布异常，单一指标可能误导，分类置信度低
        - 分歧 < 10: IVR 与 IVP 高度一致，分类置信度高

        典型高分歧场景: 财报后 IV crush（IVR=23%, IVP=85%, 分歧=62）
        """
        return abs(self.iv_rank - self.iv_pctl)


@dataclass
class DerivedBoundaries:
    """Regime 驱动的自适应参数边界。

    由 compute_derived_boundaries() 根据当前 regime 推导而来。
    决定 "用多大的望远镜去看"，而非 "看到了什么"。

    Attributes:
        default_strikes: 默认 strike 窗口宽度（strike 数量）
        default_dte: 默认 DTE 窗口上限（天）
        sigma_multiplier: 隐含波动范围的 sigma 倍数
        dte_gravity: DTE 重心方向 ("near" / "balanced" / "far")
        cache_ttl: 缓存 TTL（秒）
        confidence: 分类置信度 ("HIGH" / "LOW")
    """

    default_strikes: int
    default_dte: int
    sigma_multiplier: float
    dte_gravity: str
    cache_ttl: int
    confidence: str


def classify(regime: MarketRegime) -> RegimeClass:
    """将 MarketRegime 分类为三级市场状态。

    决策树 (设计文档 §5.3):
    1. contango < -2 → STRESS (backwardation 是最强信号，
       期限结构倒挂几乎总是伴随近端事件: 财报/FOMC/黑天鹅)
    2. iv30d > 25% AND iv_consensus > 70 → STRESS
    3. iv_consensus < 30 AND iv30d < 15% → LOW_VOL
    4. 其他 → NORMAL

    Args:
        regime: 市场状态指标集合

    Returns:
        RegimeClass: LOW_VOL, NORMAL, 或 STRESS
    """
    # Backwardation 被赋予最高决策权重——
    # 期限结构倒挂是最可靠的压力信号
    if regime.contango < -2:
        return RegimeClass.STRESS

    # 高 IV + 高共识 → 双确认压力状态
    if regime.iv30d > 0.25 and regime.iv_consensus > 70:
        return RegimeClass.STRESS

    # 低 IV + 低共识 → 低波环境
    if regime.iv_consensus < 30 and regime.iv30d < 0.15:
        return RegimeClass.LOW_VOL

    return RegimeClass.NORMAL


def compute_derived_boundaries(
    regime: MarketRegime,
    spot_price: float,
    est_strike_step: float,
) -> DerivedBoundaries:
    """根据 regime 推导参数边界。

    严格按设计文档 §5.5 的公式实现。

    Args:
        regime: 市场状态指标集合
        spot_price: 当前现货价格
        est_strike_step: 估计的 strike 间距（如 AAPL ≈ $2.5, SPY ≈ $1）

    Returns:
        DerivedBoundaries: 推导出的参数边界
    """
    regime_class = classify(regime)

    # ── DTE Window (先计算，供 implied_move 公式使用) ──

    # contango 驱动 dte_gravity:
    # backwardation (< -2) → 近端有事件压力，聚焦近月
    # 正常升水 (> +2) → 远月有更多信息价值，适度放远
    # 平坦 (-2 ~ +2) → 标准窗口
    if regime.contango < -2:
        default_dte = 30            # backwardation → 聚焦近月
        dte_gravity = "near"
    elif regime.contango > 2:
        default_dte = 75            # 正常升水 → 适度放远
        dte_gravity = "far"
    else:
        default_dte = 60            # 平坦 → 标准
        dte_gravity = "balanced"

    # ── Strike Window ──

    # iv_consensus 驱动 sigma_multiplier:
    # 高共识值 → 尾部暴露增加，需要更宽的观察窗口
    # 低共识值 → IV 可能上升，也需略宽
    if regime.iv_consensus > 70:
        sigma_multiplier = 2.5      # 高位 → 加宽（尾部暴露增加）
    elif regime.iv_consensus < 30:
        sigma_multiplier = 2.2      # 低位 → 略宽（IV 可能上升）
    else:
        sigma_multiplier = 2.0      # 正常

    # IVR 与 IVP 分歧度修正:
    # 高分歧意味着分类不确定，需保守加宽以覆盖更多尾部风险
    if regime.iv_divergence > 30:
        sigma_multiplier *= 1.1     # 安全加宽 10%

    # 隐含 1σ 波动范围 = spot × iv30d × √(dte/365) (设计文档 §13.5)
    # 使用实际 default_dte（而非固定 60）确保 STRESS/LOW_VOL 场景的窗口与期限一致
    implied_move = spot_price * regime.iv30d * sqrt(default_dte / 365)
    strike_window_width = implied_move * sigma_multiplier
    default_strikes = ceil(strike_window_width / est_strike_step)
    # 硬边界: 最少 8 个 strike（保证基本可用性），最多 30 个（控制数据量）
    default_strikes = max(8, min(30, default_strikes))

    # ── Cache TTL ──

    # volOfVol 驱动缓存 TTL，不参与边界数值计算:
    # volOfVol 衡量 IV 本身的变化速度——高 volOfVol 意味着
    # IV 快速变化，缓存数据更快过时，需要更频繁刷新
    if regime.vol_of_vol > 0.08:
        cache_ttl = 120             # 2 分钟（IV 快速变化）
    elif regime.vol_of_vol < 0.04:
        cache_ttl = 600             # 10 分钟（IV 稳定）
    else:
        cache_ttl = 300             # 5 分钟（标准）

    # 分类置信度: iv_divergence > 30 时置信度低
    confidence = "LOW" if regime.iv_divergence > 30 else "HIGH"

    return DerivedBoundaries(
        default_strikes=default_strikes,
        default_dte=default_dte,
        sigma_multiplier=sigma_multiplier,
        dte_gravity=dte_gravity,
        cache_ttl=cache_ttl,
        confidence=confidence,
    )
