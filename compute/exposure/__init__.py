"""
compute/exposure/ — Greeks Exposure 计算模块

导出泛化计算引擎和快捷方法。
"""

from .calculator import compute_dex, compute_exposure, compute_gex, compute_vex
from .models import ExposureFrame, SignConvention
from .scaling import (
    DELTA_EXPOSURE,
    GAMMA_EXPOSURE,
    RAW,
    VEGA_EXPOSURE,
    ScalingFn,
)

__all__ = [
    "compute_exposure",
    "compute_gex",
    "compute_dex",
    "compute_vex",
    "ExposureFrame",
    "SignConvention",
    "ScalingFn",
    "GAMMA_EXPOSURE",
    "DELTA_EXPOSURE",
    "VEGA_EXPOSURE",
    "RAW",
]
