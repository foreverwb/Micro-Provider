"""
infra/rate_limiter.py — 令牌桶限流器

职责: 实现 Token Bucket 算法，确保 API 请求速率不超过数据源限制。
      ORATS API 限制 1000 req/min，系统使用 800 req/min 留出安全余量。

依赖: 无内部依赖
被依赖: provider.orats (请求前调用 acquire() 获取令牌)
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """异步令牌桶限流器。

    通过令牌桶算法平滑控制请求速率，避免突发流量触发 API 限流。

    Attributes:
        capacity: 桶容量（最大令牌数）
        refill_rate: 每秒令牌补充速率
    """

    def __init__(
        self,
        # capacity=800 而非 1000: 留 20% 安全余量
        # 防止时钟漂移、并发竞争或 API 侧滑动窗口偏差导致触发限流
        capacity: float = 800.0,
        # refill_rate = 800 tokens / 60 sec ≈ 13.3 tokens/sec
        # 匀速补充令牌，确保长期平均速率不超过 800 req/min
        refill_rate: float = 800.0 / 60.0,
    ) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> float:
        """桶容量。"""
        return self._capacity

    @property
    def refill_rate(self) -> float:
        """每秒令牌补充速率。"""
        return self._refill_rate

    @property
    def tokens(self) -> float:
        """当前可用令牌数（近似值，未加锁读取）。"""
        return self._tokens

    async def acquire(self, cost: float = 1.0) -> None:
        """获取指定数量的令牌，令牌不足时异步等待。

        Args:
            cost: 本次请求消耗的令牌数，默认 1.0（单次 API 调用）

        Raises:
            ValueError: cost 超过桶容量（永远无法满足）
        """
        if cost > self._capacity:
            raise ValueError(
                f"请求成本 {cost} 超过桶容量 {self._capacity}，永远无法满足"
            )

        async with self._lock:
            self._refill()

            if self._tokens >= cost:
                # 令牌充足，直接扣减
                self._tokens -= cost
                return

            # 令牌不足，计算需要等待的时间
            deficit = cost - self._tokens
            wait_seconds = deficit / self._refill_rate

            # 释放锁后等待，避免阻塞其他协程
            # 但在锁内计算等待时间，确保一致性
            self._tokens = 0

        await asyncio.sleep(wait_seconds)

        # 等待后重新获取锁，补充令牌并扣减
        async with self._lock:
            self._refill()
            self._tokens -= cost

    def _refill(self) -> None:
        """根据流逝时间补充令牌。

        使用 monotonic clock 避免系统时间调整导致的计算错误。
        令牌数不超过桶容量。
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now

        # 按流逝时间匀速补充，上限为桶容量
        self._tokens = min(
            self._capacity,
            self._tokens + elapsed * self._refill_rate,
        )
