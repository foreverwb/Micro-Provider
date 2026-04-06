"""
compute/volatility/models.py — 波动率结构数据模型

职责: 定义 Surface/Term/Skew/Smile 构建器的输出容器。

依赖: 无内部依赖
被依赖: compute.volatility.surface, term, skew, smile
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator


class CoordType(Enum):
    """Surface X 轴坐标类型。

    IV 域使用 delta 坐标（0~100），Greeks 域使用 strike 坐标。
    """

    DELTA = "delta"
    STRIKE = "strike"


class SurfaceFrame(BaseModel):
    """二维波动率/Greeks 曲面容器。

    X 轴 = delta 或 strike（取决于 coord_type）
    Y 轴 = DTE（到期日）
    Z 值 = IV、Greek 值、或 Exposure 值

    Attributes:
        x_axis: X 轴标签（如 "delta" 或 "strike"）
        y_axis: Y 轴标签（固定为 "dte"）
        z_label: Z 值标签（如 "IV %", "GEX $"）
        data: 底层 DataFrame，行=到期日，列=X 轴刻度
        coord_type: 坐标类型 (DELTA 或 STRIKE)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    x_axis: str
    y_axis: str = "dte"
    z_label: str
    data: pd.DataFrame
    coord_type: CoordType


class TermFrame(BaseModel):
    """1D 期限结构容器。

    期限结构（term structure）展示 ATM IV 随 DTE 的变化:
    - 正常市场: 远月 IV > 近月 IV（contango / 升水）
    - 压力市场: 近月 IV > 远月 IV（backwardation / 倒挂）

    Attributes:
        df: 底层 DataFrame，必须包含 dte 和 atmiv 列。
            可选包含 expirDate（到期日）和 forecast_iv（预测 IV）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    df: pd.DataFrame

    @model_validator(mode="before")
    @classmethod
    def validate_dataframe(cls, data: Any) -> Any:
        """校验包含 dte 和 atmiv 列。"""
        df = data.get("df") if isinstance(data, dict) else getattr(data, "df", None)
        if df is None:
            raise ValueError("TermFrame 必须包含 df 字段")
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df 必须是 pandas DataFrame")

        required = {"dte", "atmiv"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"TermFrame 缺少必要列: {missing}")
        return data


class SkewFrame(BaseModel):
    """2D IV 偏斜曲线容器（X = delta 坐标）。

    Skew 使用 delta 作为 X 轴: 从 OTM put (delta≈0) 到 OTM call (delta≈100)。
    与 Smile（X=strike）的区别: skew 标准化了标的价格和到期日的影响，
    便于跨标的和跨时间比较。

    Attributes:
        df: 底层 DataFrame，必须包含 delta 和 iv 列。
            可选包含 expirDate（支持多到期日 compare 叠加）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    df: pd.DataFrame

    @model_validator(mode="before")
    @classmethod
    def validate_dataframe(cls, data: Any) -> Any:
        """校验包含 delta 和 iv 列。"""
        df = data.get("df") if isinstance(data, dict) else getattr(data, "df", None)
        if df is None:
            raise ValueError("SkewFrame 必须包含 df 字段")
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df 必须是 pandas DataFrame")

        required = {"delta", "iv"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"SkewFrame 缺少必要列: {missing}")
        return data


class SmileFrame(BaseModel):
    """2D IV 微笑曲线容器（X = strike 坐标）。

    Smile 使用 strike 作为 X 轴，展示特定到期日的 IV 曲线形态。
    与 Skew（X=delta）的区别: smile 保留了绝对价格信息，
    直观展示哪些 strike 的 IV 偏高/偏低。

    Attributes:
        df: 底层 DataFrame，必须包含 strike 列。
            可选包含 call_iv, put_iv, smv_vol 列。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    df: pd.DataFrame

    @model_validator(mode="before")
    @classmethod
    def validate_dataframe(cls, data: Any) -> Any:
        """校验包含 strike 列。"""
        df = data.get("df") if isinstance(data, dict) else getattr(data, "df", None)
        if df is None:
            raise ValueError("SmileFrame 必须包含 df 字段")
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df 必须是 pandas DataFrame")

        if "strike" not in df.columns:
            raise ValueError("SmileFrame 缺少必要列: strike")
        return data
