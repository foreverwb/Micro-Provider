"""
tests/test_provider.py — OratsProvider get_strikes 测试 (Part 1)

测试覆盖:
- get_strikes: 返回类型、字段裁剪、过滤参数、token 注入、URL 构建

get_monies / get_summary / get_ivrank / get_hist_summary / 错误处理
测试见 test_provider_data.py
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from provider.fields import (
    APIError,
    DEFAULT_STRIKES_FIELDS,
    EmptyResponseError,
    GEX_FIELDS,
)
from provider.models import (
    HistSummaryFrame,
    IVRankRecord,
    MoniesFrame,
    StrikesFrame,
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


def _error_response(status: int = 500, detail: str = "Server Error") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = detail
    return resp


def _get_params(mock_client: AsyncMock) -> dict:
    """从 mock client 的最后一次调用中提取 params。"""
    call_kwargs = mock_client.get.call_args
    # 兼容位置参数和关键字参数两种调用方式
    if call_kwargs.kwargs.get("params"):
        return call_kwargs.kwargs["params"]
    if len(call_kwargs.args) > 1:
        return call_kwargs.args[1]
    return {}


@pytest.fixture
def mock_client() -> AsyncMock:
    """返回 mock httpx.AsyncClient。"""
    return AsyncMock()


@pytest.fixture
def provider(mock_client: AsyncMock) -> OratsProvider:
    """构造带 mock client 的 OratsProvider。"""
    return OratsProvider(api_token="test-token", client=mock_client)


# ── get_strikes Tests ──


class TestGetStrikes:
    """get_strikes: strikes 端点请求与字段裁剪。"""

    @pytest.mark.asyncio
    async def test_returns_strikes_frame(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """正常响应应返回 StrikesFrame。"""
        mock_client.get.return_value = _json_response([
            {"strike": 200.0, "spotPrice": 218.5, "gamma": 0.05},
        ])
        result = await provider.get_strikes("AAPL")
        assert isinstance(result, StrikesFrame)
        assert len(result.df) == 1

    @pytest.mark.asyncio
    async def test_default_fields_trimming(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """未指定 fields 时应使用 DEFAULT_STRIKES_FIELDS。"""
        mock_client.get.return_value = _json_response([
            {"strike": 200.0, "spotPrice": 218.5},
        ])
        await provider.get_strikes("AAPL")
        params = _get_params(mock_client)
        assert "fields" in params
        assert params["fields"] == ",".join(DEFAULT_STRIKES_FIELDS)

    @pytest.mark.asyncio
    async def test_custom_fields(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """指定 fields 参数时应使用自定义字段列表。"""
        mock_client.get.return_value = _json_response([
            {"strike": 200.0, "spotPrice": 218.5},
        ])
        await provider.get_strikes("AAPL", fields=GEX_FIELDS)
        params = _get_params(mock_client)
        assert params["fields"] == ",".join(GEX_FIELDS)

    @pytest.mark.asyncio
    async def test_dte_filter_passed(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """dte 过滤参数应传递到请求。"""
        mock_client.get.return_value = _json_response([
            {"strike": 200.0, "spotPrice": 218.5},
        ])
        await provider.get_strikes("AAPL", dte="0,60")
        params = _get_params(mock_client)
        assert params["dte"] == "0,60"

    @pytest.mark.asyncio
    async def test_delta_filter_passed(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """delta 过滤参数应传递到请求。"""
        mock_client.get.return_value = _json_response([
            {"strike": 200.0, "spotPrice": 218.5},
        ])
        await provider.get_strikes("AAPL", delta="0.15,0.85")
        params = _get_params(mock_client)
        assert params["delta"] == "0.15,0.85"

    @pytest.mark.asyncio
    async def test_token_injected(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """API token 应自动注入 params。"""
        mock_client.get.return_value = _json_response([
            {"strike": 200.0, "spotPrice": 218.5},
        ])
        await provider.get_strikes("AAPL")
        params = _get_params(mock_client)
        assert params["token"] == "test-token"

    @pytest.mark.asyncio
    async def test_endpoint_url(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """请求 URL 应包含 /strikes 端点。"""
        mock_client.get.return_value = _json_response([
            {"strike": 200.0, "spotPrice": 218.5},
        ])
        await provider.get_strikes("AAPL")
        call_args = mock_client.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "/strikes" in url
