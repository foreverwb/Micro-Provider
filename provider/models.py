"""
provider/models.py — Provider 层数据模型定义

职责: 定义所有 Provider 返回的标准化数据容器。
      使用 Pydantic v2 BaseModel 包装 pandas DataFrame，
      通过 model_validator 确保必要列存在。

依赖: 无内部依赖（纯数据模型）
被依赖: provider.protocol, provider.orats,
        compute/ 层所有模块消费这些模型
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator


class StrikesFrame(BaseModel):
    """逐 strike 粒度的期权数据容器。

    包装 pandas DataFrame，每行为一个 expiry×strike 组合。
    用于 GEX/DEX/VEX 暴露计算、OI 分布、smile 构建等。

    Attributes:
        df: 底层 DataFrame，至少包含 strike、spotPrice 列，
            以及根据用途所需的 Greeks/OI 列。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    df: pd.DataFrame

    @model_validator(mode="before")
    @classmethod
    def validate_dataframe(cls, data: Any) -> Any:
        """校验 DataFrame 包含 strikes 数据的基础必要列。

        必要列: strike, spotPrice — 所有 strikes 数据操作的最小公共依赖。
        Greeks 和 OI 列按具体用途由调用方在 fields 参数中指定，
        此处仅校验结构完整性。
        """
        df = data.get("df") if isinstance(data, dict) else getattr(data, "df", None)
        if df is None:
            raise ValueError("StrikesFrame 必须包含 df 字段")
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df 必须是 pandas DataFrame")

        required_cols = {"strike", "spotPrice"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(
                f"StrikesFrame 缺少必要列: {missing}。"
                f"当前列: {list(df.columns)}"
            )
        return data


class MoniesFrame(BaseModel):
    """按到期日分组的 SMV 隐含波动率曲线容器。

    包装 pandas DataFrame，每行为一个到期日的完整 SMV 曲线。
    vol0~vol100 表示 delta 0%~100% 对应的隐含波动率。

    Attributes:
        df: 底层 DataFrame，必须包含 vol0~vol100、atmiv、slope、deriv 列。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    df: pd.DataFrame

    @model_validator(mode="before")
    @classmethod
    def validate_dataframe(cls, data: Any) -> Any:
        """校验 DataFrame 包含 SMV 曲线的必要列。

        vol0~vol100: 不同 delta 水平的 IV（21 个采样点，步长 5）
        atmiv: ATM 隐含波动率
        slope: SMV 曲线斜率（skew 的一阶近似）
        deriv: SMV 曲线二阶导数（smile 的曲率）
        """
        df = data.get("df") if isinstance(data, dict) else getattr(data, "df", None)
        if df is None:
            raise ValueError("MoniesFrame 必须包含 df 字段")
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df 必须是 pandas DataFrame")

        # vol0~vol100 以步长 5 采样，共 21 个点
        vol_cols = {f"vol{i}" for i in range(0, 101, 5)}
        structural_cols = {"atmiv", "slope", "deriv"}
        required_cols = vol_cols | structural_cols

        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(
                f"MoniesFrame 缺少必要列: {missing}。"
                f"当前列: {list(df.columns)}"
            )
        return data


class SummaryRecord(BaseModel):
    """标的级别汇总数据记录。

    平铺的 Pydantic model，包含 ATM IV 期限结构、成交量/OI 汇总、
    波动率预测、slope 结构等标的级别指标。
    字段与数据源返回的汇总端点一一对应。

    字段分组说明:
    - 基础信息: ticker, tradeDate, assetType, priorCls, mktCap
    - 成交量/OI: cVolu, cOi, pVolu, pOi (call/put volume 和 open interest)
    - ATM IV 期限结构: atmIvM1~M4, atmFitIvM1~M4, atmFcstIvM1~M4, dtExM1~M4
    - 波动率预测: orFcst20d, orIvFcst20d, orFcstInf, orIvXern20d, orIvXernInf
    - 结构指标: slope, deriv, volOfVol, px1kGam
    """

    # ── 基础信息 ──
    ticker: str
    tradeDate: str                          # 数据日期 YYYY-MM-DD
    assetType: str | None = None            # 资产类型（equity, ETF, index）
    priorCls: float | None = None           # 前收盘价
    pxAtmIv: float | None = None            # 价格隐含 ATM IV
    mktCap: float | None = None             # 市值

    # ── 成交量与持仓量 ──
    cVolu: int | None = None                # Call 成交量
    cOi: int | None = None                  # Call 持仓量
    pVolu: int | None = None                # Put 成交量
    pOi: int | None = None                  # Put 持仓量

    # ── 波动率预测 ──
    orFcst20d: float | None = None          # ORATS 20 日已实现波动率预测
    orIvFcst20d: float | None = None        # ORATS 20 日隐含波动率预测
    orFcstInf: float | None = None          # ORATS 无穷远期已实现波动率预测
    orIvXern20d: float | None = None        # 20 日排除财报的 IV
    orIvXernInf: float | None = None        # 无穷远期排除财报的 IV
    iv200Ma: float | None = None            # IV 200 日均线

    # ── ATM IV 期限结构 (M1~M4 = 近月到远月) ──
    atmIvM1: float | None = None            # 第 1 近月 ATM IV
    atmFitIvM1: float | None = None         # M1 拟合 ATM IV
    atmFcstIvM1: float | None = None        # M1 预测 ATM IV
    dtExM1: int | None = None               # M1 到期日 DTE

    atmIvM2: float | None = None
    atmFitIvM2: float | None = None
    atmFcstIvM2: float | None = None
    dtExM2: int | None = None

    atmIvM3: float | None = None
    atmFitIvM3: float | None = None
    atmFcstIvM3: float | None = None
    dtExM3: int | None = None

    atmIvM4: float | None = None
    atmFitIvM4: float | None = None
    atmFcstIvM4: float | None = None
    dtExM4: int | None = None

    # ── 利率 ──
    iRate5wk: float | None = None           # 5 周短期利率
    iRateLt: float | None = None            # 长期利率

    # ── 结构指标 ──
    px1kGam: float | None = None            # 每 1000 gamma 的价格影响
    volOfVol: float | None = None           # 波动率的波动率（驱动缓存 TTL）
    volOfIvol: float | None = None          # IV 的波动率

    slope: float | None = None              # SMV 曲线斜率（skew 一阶近似）
    slopeInf: float | None = None           # 远期 slope
    slopeFcst: float | None = None          # slope 预测
    slopeFcstInf: float | None = None       # 远期 slope 预测

    deriv: float | None = None              # SMV 曲线二阶导（smile 曲率）
    derivInf: float | None = None
    derivFcst: float | None = None
    derivFcstInf: float | None = None

    # ── 市场宽度与财报 ──
    mktWidthVol: float | None = None        # 市场报价宽度 (近月)
    mktWidthVolInf: float | None = None     # 市场报价宽度 (远期)
    ivEarnReturn: float | None = None       # IV 财报回报
    fcstR2: float | None = None             # 预测 R²
    fcstR2Imp: float | None = None          # 隐含预测 R²

    # ── 成交量统计 ──
    stkVolu: int | None = None              # 股票成交量
    avgOptVolu20d: float | None = None      # 20 日平均期权成交量

    # ── 现货价格（部分端点附带）──
    spotPrice: float | None = None


class IVRankRecord(BaseModel):
    """IV Rank 与 IV Percentile 数据记录。

    系统同时需要 iv_rank 和 iv_pctl 两个指标进行交叉验证:
    - iv_rank (IVR): 当前 IV 在 52 周极值区间的线性位置，对历史 spike 敏感
    - iv_pctl (IVP): 过去 N 日中低于当前 IV 的百分比，对分布尖峰更鲁棒
    两者合成为 iv_consensus 和 iv_divergence 用于 regime 分类。
    """

    iv_rank: float      # IVR: (当前IV - 52wk低) / (52wk高 - 52wk低)，范围 0~100
    iv_pctl: float      # IVP: 过去 N 日中低于当前 IV 的百分比，范围 0~100


class HistSummaryFrame(BaseModel):
    """历史汇总数据容器。

    包装 pandas DataFrame，用于 IV Rank 精确计算（需 52 周历史 ATM IV）
    和 earnings implied move 历史回测。每行为一个交易日的汇总数据。

    Attributes:
        df: 底层 DataFrame，至少包含 tradeDate 列。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    df: pd.DataFrame

    @model_validator(mode="before")
    @classmethod
    def validate_dataframe(cls, data: Any) -> Any:
        """校验 DataFrame 包含历史汇总的基础必要列。"""
        df = data.get("df") if isinstance(data, dict) else getattr(data, "df", None)
        if df is None:
            raise ValueError("HistSummaryFrame 必须包含 df 字段")
        if not isinstance(df, pd.DataFrame):
            raise ValueError("df 必须是 pandas DataFrame")

        if "tradeDate" not in df.columns:
            raise ValueError(
                f"HistSummaryFrame 缺少必要列: tradeDate。"
                f"当前列: {list(df.columns)}"
            )
        return data
