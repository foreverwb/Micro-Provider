"""
provider/protocol.py — DataProvider 抽象接口定义

职责: 定义所有数据源必须实现的 Protocol 接口，确保 Provider 可替换。
      上层计算模块仅依赖此 Protocol，不直接依赖任何具体实现。

依赖: provider.models (StrikesFrame, MoniesFrame, SummaryRecord, IVRankRecord, HistSummaryFrame)
被依赖: provider.orats (OratsProvider 实现此 Protocol),
        compute/ 层所有模块通过此接口获取数据
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    HistSummaryFrame,
    IVRankRecord,
    MoniesFrame,
    StrikesFrame,
    SummaryRecord,
)


@runtime_checkable
class DataProvider(Protocol):
    """数据源抽象接口。

    所有外部数据源（ORATS、IBKR、CBOE 等）必须实现此 Protocol。
    上层模块通过此接口获取标准化的期权数据，与具体数据源解耦。

    核心方法对应三个主要端点:
    - get_strikes: 逐 strike 粒度的 Greeks/OI/IV 数据
    - get_monies:  按到期日分组的 SMV 隐含波动率曲线
    - get_summary: 标的级别汇总（ATM IV、PCR、volOfVol 等）
    - get_ivrank:  IV Rank 与 IV Percentile
    - get_hist_summary: 历史汇总数据（用于 IV Rank 精确计算和回测）
    """

    async def get_strikes(
        self,
        ticker: str,
        dte: str | None = None,
        delta: str | None = None,
        fields: list[str] | None = None,
    ) -> StrikesFrame:
        """获取逐 strike 粒度的期权数据。

        Args:
            ticker: 标的代码（如 "AAPL", "SPY"）
            dte: DTE 过滤范围，格式 "min,max"（如 "0,60" 表示 0~60 天到期）。
                 None 表示不过滤。
            delta: Delta 过滤范围，格式 "min,max"（如 "0.15,0.85"）。
                   None 表示不过滤。
            fields: 请求的字段列表。必须指定以最小化网络传输。
                    None 时由实现方决定默认字段集。

        Returns:
            StrikesFrame: 包含 DataFrame 的标准化容器，
                          每行为一个 expiry×strike 组合。
        """
        ...

    async def get_monies(
        self,
        ticker: str,
        fields: list[str] | None = None,
    ) -> MoniesFrame:
        """获取按到期日分组的 SMV 隐含波动率曲线。

        返回的 MoniesFrame 包含 vol0~vol100 列，表示不同 delta 水平的
        隐含波动率，以及 atmiv、slope、deriv 等拟合参数。

        Args:
            ticker: 标的代码
            fields: 请求的字段列表。None 时返回全部字段。

        Returns:
            MoniesFrame: 每行为一个到期日的 SMV 曲线数据。
        """
        ...

    async def get_summary(self, ticker: str) -> SummaryRecord:
        """获取标的级别汇总数据。

        返回单条记录，包含 ATM IV（M1~M4）、成交量/OI 汇总、
        volOfVol、slope 等标的级别指标。

        Args:
            ticker: 标的代码

        Returns:
            SummaryRecord: 平铺的汇总数据记录。
        """
        ...

    async def get_ivrank(self, ticker: str) -> IVRankRecord:
        """获取 IV Rank 与 IV Percentile。

        两个指标衡量不同维度:
        - ivRank: 当前 IV 在 52 周极值区间的线性位置
        - ivPct:  过去 N 日中低于当前 IV 的百分比
        系统同时需要两者进行交叉验证（见 regime 模块）。

        Args:
            ticker: 标的代码

        Returns:
            IVRankRecord: 包含 iv_rank 和 iv_pctl 两个字段。
        """
        ...

    async def get_hist_summary(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> HistSummaryFrame:
        """获取历史汇总数据。

        用于 IV Rank 的精确计算（需要 52 周历史 ATM IV）
        和 earnings implied move 的历史回测。

        Args:
            ticker: 标的代码
            start_date: 起始日期，格式 "YYYY-MM-DD"
            end_date: 结束日期，格式 "YYYY-MM-DD"

        Returns:
            HistSummaryFrame: 包含历史汇总数据的 DataFrame 容器。
        """
        ...
