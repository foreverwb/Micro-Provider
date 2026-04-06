"""
tests/test_provider_data.py — OratsProvider monies/summary/ivrank 测试 (Part 2)

测试覆盖:
- get_monies: 返回类型、默认无字段裁剪、URL
- get_summary: 返回类型、空响应异常、字段映射
- get_ivrank: 返回类型、ivRank→iv_rank / ivPct→iv_pctl 映射

get_strikes 见 test_provider.py
get_hist_summary + 错误处理见 test_provider_hist.py
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from provider.fields import EmptyResponseError
from provider.models import (
    IVRankRecord,
    MoniesFrame,
    SummaryRecord,
)
from provider.orats import OratsProvider


# ── Helpers ──


def _json_response(data: list[dict], status: int = 200) -> MagicMock:
    """构造模拟 JSON 响应 (ORATS 格式: {"data": [...]})。"""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"data": data}
    resp.text = json.dumps({"data": data})
    return resp


def _get_params(mock_client: AsyncMock) -> dict:
    """从 mock client 的最后一次调用中提取 params。"""
    call_kwargs = mock_client.get.call_args
    if call_kwargs.kwargs.get("params"):
        return call_kwargs.kwargs["params"]
    if len(call_kwargs.args) > 1:
        return call_kwargs.args[1]
    return {}


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def provider(mock_client: AsyncMock) -> OratsProvider:
    return OratsProvider(api_token="test-token", client=mock_client)


# ── get_monies Tests ──


class TestGetMonies:
    """get_monies: monies/implied 端点。"""

    @pytest.mark.asyncio
    async def test_returns_monies_frame(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """正常响应应返回 MoniesFrame。"""
        vol_data: dict = {f"vol{i}": 0.25 for i in range(0, 101, 5)}
        vol_data.update({"atmiv": 0.25, "slope": -0.10, "deriv": 0.01})
        mock_client.get.return_value = _json_response([vol_data])
        result = await provider.get_monies("AAPL")
        assert isinstance(result, MoniesFrame)

    @pytest.mark.asyncio
    async def test_no_fields_by_default(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """get_monies 未指定 fields 时不应传 fields 参数（返回全量字段）。"""
        vol_data: dict = {f"vol{i}": 0.25 for i in range(0, 101, 5)}
        vol_data.update({"atmiv": 0.25, "slope": -0.10, "deriv": 0.01})
        mock_client.get.return_value = _json_response([vol_data])
        await provider.get_monies("AAPL")
        params = _get_params(mock_client)
        assert "fields" not in params

    @pytest.mark.asyncio
    async def test_endpoint_url(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """请求 URL 应包含 /monies/implied。"""
        vol_data: dict = {f"vol{i}": 0.25 for i in range(0, 101, 5)}
        vol_data.update({"atmiv": 0.25, "slope": -0.10, "deriv": 0.01})
        mock_client.get.return_value = _json_response([vol_data])
        await provider.get_monies("AAPL")
        call_args = mock_client.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "/monies/implied" in url


# ── get_summary Tests ──


class TestGetSummary:
    """get_summary: summaries 端点。"""

    @pytest.mark.asyncio
    async def test_returns_summary_record(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """正常响应应返回 SummaryRecord。"""
        mock_client.get.return_value = _json_response([
            {"ticker": "AAPL", "tradeDate": "2026-04-01", "spotPrice": 218.5},
        ])
        result = await provider.get_summary("AAPL")
        assert isinstance(result, SummaryRecord)
        assert result.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_empty_summary_raises(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """空数据应抛出 EmptyResponseError。"""
        mock_client.get.return_value = _json_response([])
        with pytest.raises(EmptyResponseError):
            await provider.get_summary("INVALID")

    @pytest.mark.asyncio
    async def test_spot_price_preserved(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """spotPrice 字段应映射到 SummaryRecord.spotPrice。"""
        mock_client.get.return_value = _json_response([
            {"ticker": "AAPL", "tradeDate": "2026-04-01", "spotPrice": 218.5},
        ])
        result = await provider.get_summary("AAPL")
        assert result.spotPrice == 218.5


# ── get_ivrank Tests ──


class TestGetIVRank:
    """get_ivrank: ivrank 端点，映射 ivRank→iv_rank, ivPct→iv_pctl。"""

    @pytest.mark.asyncio
    async def test_returns_ivrank_record(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """正常响应应返回 IVRankRecord。"""
        mock_client.get.return_value = _json_response([
            {"ivRank": 48.0, "ivPct": 52.0},
        ])
        result = await provider.get_ivrank("AAPL")
        assert isinstance(result, IVRankRecord)

    @pytest.mark.asyncio
    async def test_field_mapping_ivrank(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """ivRank → iv_rank 字段映射。"""
        mock_client.get.return_value = _json_response([
            {"ivRank": 48.0, "ivPct": 52.0},
        ])
        result = await provider.get_ivrank("AAPL")
        assert result.iv_rank == pytest.approx(48.0)

    @pytest.mark.asyncio
    async def test_field_mapping_ivpct(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """ivPct → iv_pctl 字段映射。"""
        mock_client.get.return_value = _json_response([
            {"ivRank": 48.0, "ivPct": 52.0},
        ])
        result = await provider.get_ivrank("AAPL")
        assert result.iv_pctl == pytest.approx(52.0)

    @pytest.mark.asyncio
    async def test_empty_ivrank_raises(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """空数据应抛出 EmptyResponseError。"""
        mock_client.get.return_value = _json_response([])
        with pytest.raises(EmptyResponseError):
            await provider.get_ivrank("INVALID")
