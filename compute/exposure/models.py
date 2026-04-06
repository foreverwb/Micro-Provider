"""
compute/exposure/models.py — 暴露计算数据模型

职责: 定义 Greeks Exposure 计算的输入/输出模型与枚举类型。

依赖: 无内部依赖
被依赖: compute.exposure.calculator (消费 SignConvention, 产出 ExposureFrame)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator


class SignConvention(Enum):
    """Put 侧符号约定。

    不同 Greek 暴露对 put 侧的符号处理不同:
    - NEGATE_PUT: put 侧取反。用于 GEX——因为 put gamma 的方向效应
      与 call gamma 相反: dealer long put 时 gamma 为正，但其对冲行为
      是反向的（卖出标的），所以需要取反以反映真实的市场稳定/不稳定效应。
    - KEEP_SIGN: 保持原始符号。用于 DEX（put delta 本身已为负）
      和 VEX（vega 对 call/put 同号）。
    """

    NEGATE_PUT = "negate_put"
    KEEP_SIGN = "keep_sign"


class ExposureFrame(BaseModel):
    """Greeks Exposure 计算结果容器。

    包装 pandas DataFrame，每行为一个 expiry×strike 组合的暴露值。
    下游可按 strike 聚合（gexr）、按 expiry 聚合（gexs）或全量求和（gexn）。

    Attributes:
        df: 底层 DataFrame，必须包含 exposure_value 列，
            以及用于聚合的维度列（strike, expirDate 等）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    df: pd.DataFrame

    @model_validator(mode="before")
    @classmethod
    def validate_dataframe(cls, data: Any) -> Any:
        """校验 DataFrame 包含 exposure_value 列。"""
        df = data.get("df") if isinstance(data, dict) else getattr(data, "df", None)
        if df is None:
            raise ValueError("ExposureFrame 必须包含 df 字段")
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df 必须是 pandas DataFrame")

        if "exposure_value" not in df.columns:
            raise ValueError(
                f"ExposureFrame 缺少必要列: exposure_value。"
                f"当前列: {list(df.columns)}"
            )
        return data
