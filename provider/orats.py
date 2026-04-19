"""
provider/orats.py — ORATS Delayed Data API 实现

职责: 实现 DataProvider Protocol，封装 ORATS API 的 HTTP 请求、
      格式解析（JSON/CSV）和统一错误处理。

依赖: provider.models, provider.fields (异常类 + 字段常量)
被依赖: 上层通过 DataProvider Protocol 间接使用，不直接 import 此模块
"""

from __future__ import annotations

import io
from typing import Any

import httpx
import pandas as pd

from .fields import APIError, DEFAULT_STRIKES_FIELDS, EmptyResponseError
from .models import (
    HistSummaryFrame,
    IVRankRecord,
    MoniesFrame,
    StrikesFrame,
    SummaryRecord,
)


class OratsProvider:
    """ORATS Delayed Data API 数据源实现。

    实现 DataProvider Protocol，通过 httpx.AsyncClient 异步请求 ORATS API。
    支持 JSON 和 CSV 两种响应格式，对高 OI 标的推荐使用 CSV 以减少传输体积。

    client 参数可选:
    - 若外部注入 client，Provider 不负责其生命周期（调用方管理）
    - 若不注入，Provider 在首次请求时惰性创建内部 client，并在 close() 时负责关闭

    Attributes:
        api_token: ORATS API 认证令牌
        base_url:  API 基础 URL
        client:    httpx 异步客户端实例（可选外部注入，便于连接池复用和测试 mock）
    """

    def __init__(
        self,
        api_token: str,
        client: httpx.AsyncClient | None = None,  # 可选，None 时惰性创建内部实例
        base_url: str = "https://api.orats.io/datav2",
    ) -> None:
        self._token = api_token
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None  # 标记是否由本实例负责关闭 client

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或惰性创建 HTTP 客户端。

        外部注入时直接返回；未注入时在首次调用时创建，避免在 __init__ 中建立连接。
        """
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def close(self) -> None:
        """关闭内部创建的 HTTP 客户端。

        仅当 client 由本实例内部创建时执行关闭操作；外部注入的 client 由调用方管理。
        """
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "OratsProvider":
        """支持 async with 语法，返回自身。"""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """退出 async with 块时关闭内部 client。"""
        await self.close()

    # ──────────────────────────────────────────────
    # 公共接口方法
    # ──────────────────────────────────────────────

    async def get_strikes(
        self,
        ticker: str,
        dte: str | None = None,
        delta: str | None = None,
        fields: list[str] | None = None,
    ) -> StrikesFrame:
        """获取逐 strike 粒度的期权数据。

        Args:
            ticker: 标的代码
            dte: DTE 过滤范围 "min,max"（如 "0,60"）
            delta: Delta 过滤范围 "min,max"（如 "0.15,0.85"）
            fields: 请求字段列表。强烈建议指定，避免获取全量 40+ 字段。

        Returns:
            StrikesFrame: 标准化的 strikes 数据容器
        """
        params: dict[str, Any] = {"ticker": ticker}

        # 服务端过滤: dte 和 delta 范围由 API 侧处理，减少传输量
        if dte is not None:
            params["dte"] = dte
        if delta is not None:
            params["delta"] = delta

        # 字段裁剪: 必须指定 fields 以最小化网络传输 (设计文档 §4.3)
        selected_fields = fields or DEFAULT_STRIKES_FIELDS
        params["fields"] = ",".join(selected_fields)

        df = await self._request("/strikes", params)
        return StrikesFrame(df=df)

    async def get_monies(
        self,
        ticker: str,
        fields: list[str] | None = None,
    ) -> MoniesFrame:
        """获取按到期日分组的 SMV 隐含波动率曲线。

        Args:
            ticker: 标的代码
            fields: 请求字段列表。None 时返回全部字段。

        Returns:
            MoniesFrame: 标准化的 monies 数据容器
        """
        params: dict[str, Any] = {"ticker": ticker}
        if fields is not None:
            params["fields"] = ",".join(fields)

        df = await self._request("/monies/implied", params)
        return MoniesFrame(df=df)

    async def get_summary(self, ticker: str) -> SummaryRecord:
        """获取标的级别汇总数据。

        summaries 端点对每个 ticker 仅返回单行，无需字段裁剪。

        Args:
            ticker: 标的代码

        Returns:
            SummaryRecord: 平铺的汇总数据记录
        """
        df = await self._request("/summaries", {"ticker": ticker})
        if df.empty:
            raise EmptyResponseError(f"No summary data for {ticker}")

        # 取第一行转为字典，构建 SummaryRecord
        row = df.iloc[0].to_dict()
        return SummaryRecord(**row)

    async def get_ivrank(self, ticker: str) -> IVRankRecord:
        """获取 IV Rank 与 IV Percentile。

        ivrank 端点返回单行，包含 ivRank 和 ivPct 两个字段。
        两者都需要——用于 regime 模块的 IVR+IVP 交叉验证。

        Args:
            ticker: 标的代码

        Returns:
            IVRankRecord: 包含 iv_rank 和 iv_pctl
        """
        df = await self._request("/ivrank", {"ticker": ticker})
        if df.empty:
            raise EmptyResponseError(f"No IV rank data for {ticker}")

        row = df.iloc[0]
        return IVRankRecord(
            iv_rank=float(row["ivRank"]),
            iv_pctl=float(row["ivPct"]),
        )

    async def get_hist_summary(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> HistSummaryFrame:
        """获取历史汇总数据。

        Args:
            ticker: 标的代码
            start_date: 起始日期 "YYYY-MM-DD"
            end_date: 结束日期 "YYYY-MM-DD"

        Returns:
            HistSummaryFrame: 历史汇总数据容器
        """
        params: dict[str, Any] = {
            "ticker": ticker,
            "tradeDate": f"{start_date},{end_date}",
        }
        df = await self._request("/hist/summaries", params)
        return HistSummaryFrame(df=df)

    # ──────────────────────────────────────────────
    # 内部请求方法
    # ──────────────────────────────────────────────

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any],
        use_csv: bool = False,
    ) -> pd.DataFrame:
        """统一的 HTTP 请求方法。

        支持 JSON 和 CSV 两种响应格式:
        - JSON: 默认格式，适合小数据量请求
        - CSV:  对高 OI 标的（SPX/SPY）可减少约 40% 传输体积 (设计文档 §4.4)

        Args:
            endpoint: API 端点路径（如 "/strikes"）
            params: 查询参数字典
            use_csv: 是否使用 CSV 格式请求

        Returns:
            pd.DataFrame: 解析后的数据

        Raises:
            APIError: HTTP 非 2xx 响应
            EmptyResponseError: API 返回空数据集
        """
        params["token"] = self._token

        # CSV 格式通过在端点后追加 .csv 后缀请求
        url = f"{self._base_url}{endpoint}"
        if use_csv:
            url += ".csv"

        client = await self._get_client()
        response = await client.get(url, params=params)

        # 统一错误处理: HTTP 错误转为自定义异常
        if response.status_code != 200:
            raise APIError(
                status_code=response.status_code,
                detail=response.text[:500],
            )

        if use_csv:
            # CSV 格式用 pandas 直接解析，无重复字段名开销
            return pd.read_csv(io.StringIO(response.text))

        # JSON 格式: ORATS 返回 {"data": [...]} 结构
        payload = response.json()
        data = payload.get("data", [])
        if not data:
            raise EmptyResponseError(
                f"Empty response from {endpoint} for params {params}"
            )

        return pd.DataFrame(data)
