"""
tests/test_provider_hist.py — OratsProvider hist_summary + 错误处理测试 (Part 3)

测试覆盖:
- get_hist_summary: 返回类型、日期格式、URL
- 错误处理: HTTP 非 2xx → APIError，空响应 → EmptyResponseError

get_strikes 见 test_provider.py
get_monies / get_summary / get_ivrank 见 test_provider_data.py
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from provider.fields import APIError, EmptyResponseError
from provider.models import HistSummaryFrame
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


# ── get_hist_summary Tests ──


class TestGetHistSummary:
    """get_hist_summary: hist/summaries 端点。"""

    @pytest.mark.asyncio
    async def test_returns_hist_summary_frame(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """正常响应应返回 HistSummaryFrame。"""
        mock_client.get.return_value = _json_response([
            {"tradeDate": "2025-04-01", "ticker": "AAPL", "atmIvM1": 0.22},
            {"tradeDate": "2025-04-02", "ticker": "AAPL", "atmIvM1": 0.23},
        ])
        result = await provider.get_hist_summary("AAPL", "2025-04-01", "2025-04-02")
        assert isinstance(result, HistSummaryFrame)
        assert len(result.df) == 2

    @pytest.mark.asyncio
    async def test_date_params_format(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """tradeDate 应为 "start,end" 格式（ORATS 范围查询语法）。"""
        mock_client.get.return_value = _json_response([
            {"tradeDate": "2025-04-01"},
        ])
        await provider.get_hist_summary("AAPL", "2025-04-01", "2025-09-30")
        params = _get_params(mock_client)
        assert params["tradeDate"] == "2025-04-01,2025-09-30"

    @pytest.mark.asyncio
    async def test_endpoint_url(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """请求 URL 应包含 /hist/summaries。"""
        mock_client.get.return_value = _json_response([
            {"tradeDate": "2025-04-01"},
        ])
        await provider.get_hist_summary("AAPL", "2025-04-01", "2025-04-30")
        call_args = mock_client.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "/hist/summaries" in url


# ── Error Handling Tests ──


class TestErrorHandling:
    """HTTP 错误和空响应处理。"""

    @pytest.mark.asyncio
    async def test_http_error_raises_api_error(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """非 200 状态码应抛出 APIError。"""
        mock_client.get.return_value = _error_response(429, "Rate limited")
        with pytest.raises(APIError) as exc_info:
            await provider.get_strikes("AAPL")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_api_error_preserves_detail(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """APIError 应保留响应 body 中的错误信息。"""
        mock_client.get.return_value = _error_response(500, "Internal Server Error")
        with pytest.raises(APIError) as exc_info:
            await provider.get_strikes("AAPL")
        assert "Internal Server Error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_404_raises_api_error(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """404 应抛出 APIError，状态码为 404。"""
        mock_client.get.return_value = _error_response(404, "Not Found")
        with pytest.raises(APIError) as exc_info:
            await provider.get_strikes("AAPL")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_json_data_raises(
        self, provider: OratsProvider, mock_client: AsyncMock
    ):
        """JSON 响应 data=[] 应抛出 EmptyResponseError。"""
        mock_client.get.return_value = _json_response([])
        with pytest.raises(EmptyResponseError):
            await provider.get_strikes("AAPL")
