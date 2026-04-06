"""
compute/exposure/calculator.py — 泛化的 Greeks Exposure 计算引擎

职责: 提供 compute_exposure() 方法，支持 GEX/DEX/VEX 三种暴露计算。
      所有暴露计算共享此入口，通过 scaling_fn 和 sign_convention 参数区分。

依赖: compute.exposure.scaling (缩放函数),
      compute.exposure.models (ExposureFrame, SignConvention),
      provider.models (StrikesFrame)
被依赖: compute.volatility.surface (GreekSurfaceStrategy 调用 compute_exposure)
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from provider.models import StrikesFrame
from .models import ExposureFrame, SignConvention
from .scaling import DELTA_EXPOSURE, GAMMA_EXPOSURE, VEGA_EXPOSURE, ScalingFn


def compute_exposure(
    strikes_frame: StrikesFrame,
    greek: Literal["gamma", "delta", "vega"],
    scaling_fn: ScalingFn,
    sign_convention: SignConvention,
) -> ExposureFrame:
    """泛化的 Greeks Exposure 计算方法。

    所有 GEX/DEX/VEX 共享此方法，通过参数区分:
    - greek: 使用哪个 Greek 值
    - scaling_fn: 缩放函数，将 Greek 转换为美元暴露
    - sign_convention: put 侧符号约定

    计算步骤 (以 GEX 为例):
    1. scale = scaling_fn(spotPrice) → spot² × 0.01 × 100
    2. call_exposure = gamma × callOI × scale
    3. put_exposure  = gamma × putOI  × scale × (-1)  [NEGATE_PUT]
    4. net_exposure  = call_exposure + put_exposure

    Args:
        strikes_frame: 逐 strike 粒度的期权数据
        greek: 使用的 Greek 列名 ("gamma", "delta", "vega")
        scaling_fn: 缩放函数 (spot → 缩放因子)
        sign_convention: put 侧符号约定

    Returns:
        ExposureFrame: 包含 exposure_value 列的结果，
                       保留 strike, expirDate 等维度列供下游聚合。
    """
    df = strikes_frame.df.copy()

    # Step 1: 计算缩放因子
    # spotPrice 是每行独立的（不同到期日可能观测到不同 spot，通常相同）
    scale = df["spotPrice"].apply(scaling_fn)

    # Step 2: 确定 call 侧和 put 侧的 Greek 值
    # gamma/vega 对 call 和 put 相同，但 delta 不同:
    # API 的 delta 列是 call delta (0~1)，put delta = call_delta - 1
    call_greek = df[greek]
    if greek == "delta":
        # put delta = call_delta - 1 (如 call_delta=0.70 → put_delta=-0.30)
        put_greek = df[greek] - 1
    else:
        # gamma, vega 对 call/put 相同（二阶导和 vega 是对称的）
        put_greek = df[greek]

    # Step 3: Call 侧暴露 = call_greek × callOI × scale
    call_exposure = call_greek * df["callOpenInterest"] * scale

    # Step 4: Put 侧暴露 = put_greek × putOI × scale
    put_exposure = put_greek * df["putOpenInterest"] * scale

    # Step 5: 应用符号约定
    if sign_convention == SignConvention.NEGATE_PUT:
        # GEX: put 侧取反——put gamma 的方向效应与 call gamma 相反
        # Dealer long put 的 gamma 对冲方向是卖出标的（不稳定），
        # 与 long call 的 gamma 对冲方向（买入标的，稳定）相反
        put_exposure = put_exposure * -1

    # DEX: KEEP_SIGN — put delta 已通过 (call_delta - 1) 转为负值
    # VEX: KEEP_SIGN — vega 对 call/put 同号，无需调整

    # Step 6: 净暴露 = call + put
    df["call_exposure"] = call_exposure
    df["put_exposure"] = put_exposure
    df["exposure_value"] = call_exposure + put_exposure

    # 保留维度列供下游聚合 (gexr→strike, gexs→expirDate, gexn→全量求和)
    keep_cols = ["exposure_value", "call_exposure", "put_exposure"]
    for col in ("strike", "expirDate", "dte", "spotPrice"):
        if col in df.columns:
            keep_cols.append(col)

    return ExposureFrame(df=df[keep_cols])


def compute_gex(strikes_frame: StrikesFrame) -> ExposureFrame:
    """计算 Gamma Exposure (GEX)。

    GEX = gamma × OI × spotPrice² × 0.01 × 100
    Put 侧取反（方向效应相反）。

    Args:
        strikes_frame: 包含 gamma, callOpenInterest, putOpenInterest, spotPrice 的数据

    Returns:
        ExposureFrame: GEX 暴露结果
    """
    return compute_exposure(
        strikes_frame,
        greek="gamma",
        scaling_fn=GAMMA_EXPOSURE,
        sign_convention=SignConvention.NEGATE_PUT,
    )


def compute_dex(strikes_frame: StrikesFrame) -> ExposureFrame:
    """计算 Delta Exposure (DEX)。

    DEX = delta × OI × spotPrice × 100
    Put delta 已为负值，无需额外取反。

    Args:
        strikes_frame: 包含 delta, callOpenInterest, putOpenInterest, spotPrice 的数据

    Returns:
        ExposureFrame: DEX 暴露结果
    """
    return compute_exposure(
        strikes_frame,
        greek="delta",
        scaling_fn=DELTA_EXPOSURE,
        sign_convention=SignConvention.KEEP_SIGN,
    )


def compute_vex(strikes_frame: StrikesFrame) -> ExposureFrame:
    """计算 Vega Exposure (VEX)。

    VEX = vega × OI × 100
    Vega 对 call/put 同号，无需取反。

    Args:
        strikes_frame: 包含 vega, callOpenInterest, putOpenInterest, spotPrice 的数据

    Returns:
        ExposureFrame: VEX 暴露结果
    """
    return compute_exposure(
        strikes_frame,
        greek="vega",
        scaling_fn=VEGA_EXPOSURE,
        sign_convention=SignConvention.KEEP_SIGN,
    )
