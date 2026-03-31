"""
provider/fields.py — 字段裁剪常量与异常类定义

职责: 集中定义 Provider 层公用的异常类和按命令用途裁剪的字段集常量。
      将这些从 orats.py 中拆出，使 OratsProvider 实现聚焦于 HTTP 逻辑。

依赖: 无内部依赖
被依赖: provider.orats (引用字段常量和异常类)
"""

from __future__ import annotations


# ──────────────────────────────────────────────
# 异常类
# ──────────────────────────────────────────────


class ProviderError(Exception):
    """数据源请求异常基类。"""


class APIError(ProviderError):
    """HTTP 层面的 API 错误（非 2xx 状态码）。"""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class EmptyResponseError(ProviderError):
    """API 返回空数据集。"""


# ──────────────────────────────────────────────
# 按命令用途裁剪的默认字段集
# 设计文档 §4.3: 字段裁剪策略，最小化网络传输
# ──────────────────────────────────────────────

# GEX 计算所需最小字段集
GEX_FIELDS = [
    "tradeDate", "expirDate", "dte", "strike",
    "gamma", "callOpenInterest", "putOpenInterest", "spotPrice",
]

# DEX 计算: 将 gamma 替换为 delta
DEX_FIELDS = [
    "tradeDate", "expirDate", "dte", "strike",
    "delta", "callOpenInterest", "putOpenInterest", "spotPrice",
]

# VEX 计算: 将 gamma 替换为 vega
VEX_FIELDS = [
    "tradeDate", "expirDate", "dte", "strike",
    "vega", "callOpenInterest", "putOpenInterest", "spotPrice",
]

# IV Surface 构建所需字段
IV_SURFACE_FIELDS = [
    "expirDate", "dte", "strike",
    "callMidIv", "putMidIv", "smvVol", "delta", "spotPrice",
]

# OI 分布所需字段
OI_FIELDS = [
    "expirDate", "dte", "strike",
    "callOpenInterest", "putOpenInterest", "spotPrice",
]

# 合并所有可能用到的 strikes 字段，作为未指定 fields 时的默认值
DEFAULT_STRIKES_FIELDS = sorted(
    set(GEX_FIELDS + DEX_FIELDS + VEX_FIELDS + IV_SURFACE_FIELDS + OI_FIELDS)
)
