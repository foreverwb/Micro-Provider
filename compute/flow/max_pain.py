"""
compute/flow/max_pain.py — Max Pain 计算

职责: 计算 max pain strike — 期权卖方（writer）总损失最小化的行权价。

依赖: 无内部依赖（使用 pandas DataFrame）
被依赖: commands/ 层 maxpain 命令

Max Pain 理论: 期权到期时，标的价格倾向于收敛至使期权买方总内在价值
最小（即卖方总赔付最小）的 strike。虽然争议较大，但在实践中作为
OI 加权的「引力中心」仍有参考价值。
"""

from __future__ import annotations

import pandas as pd


def compute_max_pain(
    strikes_df: pd.DataFrame,
    spot_price: float,
) -> tuple[float, pd.DataFrame]:
    """计算 Max Pain strike 和 pain curve。

    对每个候选 strike，计算假设标的在该 strike 到期时
    所有 call OI 和 put OI 的总内在价值（即卖方总赔付）。
    Max Pain = 总赔付最小的 strike。

    计算逻辑:
    - 对于候选 settlement_price S:
      - 每个 call (strike K): 如果 S > K, 内在价值 = (S - K) × callOI × 100
      - 每个 put  (strike K): 如果 S < K, 内在价值 = (K - S) × putOI × 100
      - total_pain(S) = Σ call_pain + Σ put_pain

    Args:
        strikes_df: 包含 strike, callOpenInterest, putOpenInterest 列的 DataFrame。
                    应为单一到期日的数据。
        spot_price: 当前现货价格（仅用于参考标注，不参与计算）

    Returns:
        tuple: (max_pain_strike, pain_curve_df)
            - max_pain_strike: 使总 pain 最小的 strike
            - pain_curve_df: 完整 pain 曲线，包含 strike, call_pain,
              put_pain, total_pain 列
    """
    unique_strikes = sorted(strikes_df["strike"].unique())

    pain_rows = []
    for candidate in unique_strikes:
        # Call pain: 当 settlement > strike 时，call holder 获利
        # call_pain = Σ max(0, candidate - K) × callOI × 100
        call_pain = (
            strikes_df.apply(
                lambda row: max(0, candidate - row["strike"])
                * row["callOpenInterest"]
                * 100,  # 每张合约 100 股
                axis=1,
            ).sum()
        )

        # Put pain: 当 settlement < strike 时，put holder 获利
        # put_pain = Σ max(0, K - candidate) × putOI × 100
        put_pain = (
            strikes_df.apply(
                lambda row: max(0, row["strike"] - candidate)
                * row["putOpenInterest"]
                * 100,
                axis=1,
            ).sum()
        )

        pain_rows.append({
            "strike": candidate,
            "call_pain": call_pain,
            "put_pain": put_pain,
            "total_pain": call_pain + put_pain,
        })

    pain_curve = pd.DataFrame(pain_rows)

    # Max Pain = total_pain 最小的 strike
    min_idx = pain_curve["total_pain"].idxmin()
    max_pain_strike = pain_curve.loc[min_idx, "strike"]

    return float(max_pain_strike), pain_curve
