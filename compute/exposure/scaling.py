"""
compute/exposure/scaling.py — Greeks Exposure 缩放函数

职责: 定义每种 Greek 暴露的缩放公式。
      新增 Greek 暴露类型只需在此添加一个缩放函数，无需修改 calculator。

依赖: 无内部依赖
被依赖: compute.exposure.calculator (传入 compute_exposure 的 scaling_fn 参数)

缩放函数类型签名: (spot_price: float) -> float
返回值乘以 greek_value × OI 得到美元暴露值。
"""

from __future__ import annotations

from typing import Callable

# 缩放函数类型别名
ScalingFn = Callable[[float], float]

# GEX 缩放: spot² × 0.01 × 100
# 物理含义: gamma 是 delta 对标的价格的二阶导数 (∂²V/∂S²)
# 乘以 spot² × 0.01 将 gamma 转换为「标的价格变动 1% 时 delta 的变化量」
# 再乘以 100（每张合约 100 股）得到合约级别的美元暴露
# 量纲: [1/$ ] × [$²] × [无量纲] × [股/合约] = [$]
GAMMA_EXPOSURE: ScalingFn = lambda spot: spot ** 2 * 0.01 * 100

# DEX 缩放: spot × 100
# 物理含义: delta 是期权价格对标的价格的一阶导数 (∂V/∂S)
# 乘以 spot 将 delta 转换为美元 delta
# 再乘以 100（每张合约 100 股）得到合约级别的方向性暴露
# 量纲: [无量纲] × [$] × [股/合约] = [$]
DELTA_EXPOSURE: ScalingFn = lambda spot: spot * 100

# VEX 缩放: 100 (常数)
# 物理含义: vega 本身已是「IV 变动 1% 时期权价格的变化量」($/vol点)
# 只需乘以 100（每张合约 100 股）得到合约级别的 vega 暴露
# 不需要 spot 参与缩放——vega 的量纲已经是美元
# 量纲: [$/vol点] × [股/合约] = [$/vol点]
VEGA_EXPOSURE: ScalingFn = lambda spot: 100

# RAW: 不缩放，返回原始 Greek 值
# 用于 surface 视图中直接展示 gamma/delta/vega/theta 原值
RAW: ScalingFn = lambda spot: 1.0
