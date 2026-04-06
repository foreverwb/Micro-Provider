"""
compute/flow/pcr.py — Put/Call Ratio 计算

职责: 从 SummaryRecord 计算 Volume PCR 和 OI PCR。

依赖: provider.models (SummaryRecord)
被依赖: commands/ 层 pcr 和 snap 命令

PCR 解读:
- PCR > 1: put 活跃度高于 call，市场偏看跌/对冲需求强
- PCR < 1: call 活跃度高于 put，市场偏看涨
- PCR ≈ 0.7: 美股历史均值附近（正常水平）
"""

from __future__ import annotations

from provider.models import SummaryRecord


def compute_pcr(summary: SummaryRecord) -> tuple[float | None, float | None]:
    """计算 Volume PCR 和 OI PCR。

    Args:
        summary: 标的级别汇总数据，包含 cVolu/pVolu/cOi/pOi

    Returns:
        tuple: (vol_pcr, oi_pcr)
            - vol_pcr: Put Volume / Call Volume，None if data missing
            - oi_pcr:  Put OI / Call OI，None if data missing
    """
    # Volume PCR = putVolume / callVolume
    vol_pcr = None
    if summary.pVolu is not None and summary.cVolu is not None:
        if summary.cVolu > 0:
            vol_pcr = summary.pVolu / summary.cVolu

    # OI PCR = putOI / callOI
    oi_pcr = None
    if summary.pOi is not None and summary.cOi is not None:
        if summary.cOi > 0:
            oi_pcr = summary.pOi / summary.cOi

    return vol_pcr, oi_pcr
