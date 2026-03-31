"""
infra/cache.py — 分层缓存管理器

职责: 提供 L1 进程内缓存（dict + TTL），支持 regime-aware 动态 TTL 调整
      和 stale 数据降级返回。L2 Redis 接口预留但不在本阶段实现。

依赖: 无内部依赖
被依赖: provider.orats (缓存 API 响应), compute/ 层可选使用

设计参考:
  - 缓存键格式: {ticker}:{endpoint}:{fields_hash}:{filter_hash} (设计文档 §9.2)
  - TTL 由 regime.vol_of_vol 驱动 (设计文档 §5.5):
    vol_of_vol > 0.08 → 120s, < 0.04 → 600s, 其他 → 300s
  - stale 数据超过 1 小时拒绝返回 (设计文档 §9.3)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


# stale 数据阈值: 超过 1 小时的缓存数据被视为不可靠
# 即使 API 故障，也不应返回超过 1 小时的旧数据——
# 期权 Greeks 和 IV 在 1 小时内可能已发生显著变化
STALE_THRESHOLD_SECONDS = 3600


@dataclass
class CacheEntry:
    """单条缓存条目。

    Attributes:
        value: 缓存的数据对象
        created_at: 创建时间戳 (monotonic)
        ttl: 生存时间（秒）
    """

    value: Any
    created_at: float
    ttl: float

    @property
    def is_expired(self) -> bool:
        """判断是否已过 TTL。"""
        return (time.monotonic() - self.created_at) > self.ttl

    @property
    def is_stale(self) -> bool:
        """判断是否已超过 stale 阈值（1 小时）。

        stale 阈值独立于 TTL: 即使 TTL 过期，
        如果未超过 stale 阈值，仍可作为降级数据返回。
        """
        return (time.monotonic() - self.created_at) > STALE_THRESHOLD_SECONDS

    @property
    def age_seconds(self) -> float:
        """缓存条目的存活时长（秒）。"""
        return time.monotonic() - self.created_at


@dataclass
class CacheResult:
    """缓存查询结果。

    Attributes:
        value: 缓存数据，未命中时为 None
        hit: 是否命中有效缓存
        stale: 是否为 stale 降级数据（TTL 已过但未超过 stale 阈值）
    """

    value: Any = None
    hit: bool = False
    stale: bool = False


class CacheManager:
    """L1 进程内缓存管理器。

    使用 dict + TTL 实现进程内缓存。支持:
    - regime-aware 动态 TTL (set_ttl)
    - stale 数据降级返回（API 故障时返回过期但未 stale 的数据）
    - 统一的缓存键格式

    缓存键格式: {ticker}:{endpoint}:{fields_hash}:{filter_hash}
    """

    def __init__(self, default_ttl: float = 300.0) -> None:
        self._store: dict[str, CacheEntry] = {}
        # 默认 TTL 300 秒（5 分钟），对应 NORMAL regime 下的缓存策略
        self._default_ttl = default_ttl

    @property
    def default_ttl(self) -> float:
        """当前默认 TTL（秒）。"""
        return self._default_ttl

    def set_ttl(self, ttl: float) -> None:
        """设置默认 TTL，支持 regime-aware 动态调整。

        由 regime 模块调用，根据 vol_of_vol 设置:
        - vol_of_vol > 0.08 → ttl=120  (IV 快速变化，频繁刷新)
        - vol_of_vol < 0.04 → ttl=600  (IV 稳定，延长缓存)
        - 其他              → ttl=300  (标准)

        Args:
            ttl: 新的默认 TTL（秒）
        """
        self._default_ttl = ttl

    def get(self, key: str, allow_stale: bool = False) -> CacheResult:
        """查询缓存。

        Args:
            key: 缓存键
            allow_stale: 是否允许返回 stale 降级数据。
                         用于 API 故障时的容灾降级。

        Returns:
            CacheResult: 包含 value、hit、stale 三个字段。
                         未命中时 value=None, hit=False。
        """
        entry = self._store.get(key)
        if entry is None:
            return CacheResult()

        if not entry.is_expired:
            # TTL 内: 正常命中
            return CacheResult(value=entry.value, hit=True, stale=False)

        if allow_stale and not entry.is_stale:
            # TTL 已过但未超过 stale 阈值: 降级返回
            return CacheResult(value=entry.value, hit=True, stale=True)

        # TTL 已过且不允许 stale，或已超过 stale 阈值: 未命中
        return CacheResult()

    def put(self, key: str, value: Any, ttl: float | None = None) -> None:
        """写入缓存。

        Args:
            key: 缓存键
            value: 要缓存的数据
            ttl: 自定义 TTL（秒）。None 时使用 default_ttl。
        """
        self._store[key] = CacheEntry(
            value=value,
            created_at=time.monotonic(),
            ttl=ttl if ttl is not None else self._default_ttl,
        )

    def invalidate(self, key: str) -> bool:
        """失效指定缓存条目。

        Args:
            key: 缓存键

        Returns:
            bool: 是否成功移除（键存在返回 True）
        """
        return self._store.pop(key, None) is not None

    def clear(self) -> None:
        """清空所有缓存。"""
        self._store.clear()

    @property
    def size(self) -> int:
        """当前缓存条目数量。"""
        return len(self._store)

    @staticmethod
    def build_key(
        ticker: str,
        endpoint: str,
        fields: list[str] | None = None,
        filters: dict[str, str] | None = None,
    ) -> str:
        """构建标准化缓存键。

        格式: {ticker}:{endpoint}:{fields_hash}:{filter_hash}
        使用 MD5 前 8 位作为 hash，平衡可读性和碰撞概率。

        Args:
            ticker: 标的代码
            endpoint: API 端点名（如 "strikes", "monies"）
            fields: 请求的字段列表
            filters: 过滤参数字典（如 {"dte": "0,60", "delta": "0.15,0.85"}）

        Returns:
            str: 格式化的缓存键
        """
        # 字段 hash: 排序后取 MD5 前 8 位，确保相同字段集产生相同 hash
        if fields:
            fields_str = ",".join(sorted(fields))
            fields_hash = hashlib.md5(fields_str.encode()).hexdigest()[:8]
        else:
            fields_hash = "full"

        # 过滤条件 hash: 排序键值对后取 MD5 前 8 位
        if filters:
            filter_str = "&".join(
                f"{k}={v}" for k, v in sorted(filters.items())
            )
            filter_hash = hashlib.md5(filter_str.encode()).hexdigest()[:8]
        else:
            filter_hash = "no_filter"

        return f"{ticker}:{endpoint}:{fields_hash}:{filter_hash}"
