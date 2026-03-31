# Options Microstructure Provider — 详细设计方案

> **版本**: v1.2  
> **日期**: 2026-03-31  
> **定位**: 基于 ORATS Delayed Data API 构建的期权仓位暴露与隐含波动率结构数据服务

---

## 目录

1. [项目概述与目标](#1-项目概述与目标)
2. [ORATS API 可行性评估](#2-orats-api-可行性评估)
3. [总体架构设计](#3-总体架构设计)
4. [Provider 层设计](#4-provider-层设计)
5. [Regime-Aware 自适应边界](#5-regime-aware-自适应边界)
6. [计算层设计](#6-计算层设计)
7. [命令层设计](#7-命令层设计)
8. [统一参数体系](#8-统一参数体系)
9. [缓存与基础设施设计](#9-缓存与基础设施设计)
10. [数据流汇总](#10-数据流汇总)
11. [风险与权衡](#11-风险与权衡)
12. [实施优先级](#12-实施优先级)
13. [附录](#13-附录)

---

## 1. 项目概述与目标

### 1.1 项目定位

构建一套基于 Python 的 **Options Microstructure Data Provider**，提供期权 Greeks Exposure（GEX/DEX/VEX）和 Volatility Structure（Skew/Surface/Term）的数据计算与查询服务。

### 1.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **高内聚、低耦合** | Provider 只管取数据、Computation 只管计算、Command 只管参数与输出 |
| **网络请求最小化** | 字段裁剪、缓存预热、参数精确过滤 |
| **计算逻辑复用** | CLI 与 API 共享同一计算路径，杜绝逻辑分叉 |
| **可扩展性** | 抽象 Provider 接口，日后可替换数据源；MetricRegistry 注册表驱动新指标扩展 |

### 1.3 数据源

- **主数据源**: ORATS Delayed Data API (`https://api.orats.io/datav2`)
- **数据延迟**: 15 分钟
- **API 限流**: 1000 requests/min
- **覆盖范围**: 5000+ 美股期权标的，历史数据回溯至 2007 年

---

## 2. ORATS API 可行性评估

### 2.1 端点与命令映射

系统所有命令所需的原始数据均可从 ORATS 的三个核心端点获取：

| ORATS 端点 | 返回内容 | 服务的命令 | 数据粒度 |
|------------|---------|-----------|---------|
| `GET /strikes` | 逐 strike 的 Greeks + OI + IV + 价格 | gexr, gexn, gexs, dex, dexn, vex, vexn, oi, maxpain, unusual, smile, surface(Greeks) | 每 expiry × 每 strike 一行 |
| `GET /monies/implied` | 按 expirDate 分组的 SMV 曲线 (vol0~vol100, atmiv, slope, deriv) | skew, surface(IV), term | 每 expiry 一行 |
| `GET /summaries` | 标的级别汇总 (atmIvM1~4, slope, px1kGam, volOfVol, earnings) | term, pcr, vvol, earn, snap + 所有命令的元数据 | 整个 ticker 一行 |

辅助端点：

| ORATS 端点 | 用途 | 服务的命令 |
|------------|------|-----------|
| `GET /ivrank` | IV Rank 与 IV Percentile | ivrank, snap, regime 分类 |
| `GET /hist/summaries` | 历史汇总数据 | ivrank(精确计算), ermv --history |

### 2.2 数据完备性验证

| 命令 | 所需核心字段 | ORATS 覆盖 | 计算复杂度 |
|------|-------------|-----------|-----------|
| GEX (gexr/gexn/gexs) | gamma, callOI, putOI, stockPrice, strike | ✅ 全部直接提供 | 中 |
| DEX (dex/dexn) | delta, callOI, putOI | ✅ 全部直接提供 | 低 |
| VEX (vex/vexn) | vega, callOI, putOI | ✅ 全部直接提供 | 低 |
| skew | 各 delta 水平的 IV | ✅ monies 提供 vol0~vol100 + slope/deriv | 低 |
| surface | 多到期日 × 多 delta/strike 的指标矩阵 | ✅ monies + strikes 组合覆盖 | 低~中 |
| term | 各到期日的 ATM IV | ✅ monies 的 per-expiry atmiv | 极低 |

### 2.3 已知局限性

| 局限 | 影响 | 缓解策略 |
|------|------|---------|
| ORATS 不直接提供 GEX/DEX/VEX 暴露值 | 需要在 Provider 层自行计算 | 反而更好——可控制公式变体 |
| Delayed API 15 分钟延迟 | 盘中实时监控精度不足 | 对 Bot 快照场景足够；Live API 作为升级路径 |
| SPX/SPY 等标的 strikes 数据量大（3000+行） | 解析慢，带宽高 | fields 裁剪 + dte/delta 过滤 + CSV 格式 |
| monies/implied 可能不覆盖极近到期（0DTE） | skew/surface 缺少部分到期日 | Fallback 到 /strikes 端点逐 strike 计算 |

---

## 3. 总体架构设计

### 3.1 分层架构

```
┌───────────────────────────────────────────────────────────────────┐
│                      Command Layer                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Exposure  │ │ Surface  │ │ Analytics│ │ Composite│            │
│  │ Commands  │ │ Commands │ │ Commands │ │ Commands │            │
│  │ gexr/n/s  │ │ surface  │ │ ivrank   │ │ snap     │            │
│  │ dex/n     │ │ skew     │ │ vvol     │ │ unusual  │            │
│  │ vex/n     │ │ smile    │ │ pcr      │ │          │            │
│  │           │ │ term     │ │ earn/ermv│ │          │            │
│  │           │ │          │ │ oi       │ │          │            │
│  │           │ │          │ │ maxpain  │ │          │            │
│  └─────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
├────────┴─────────────┴────────────┴─────────────┴────────────────┤
│                    Computation Layer                               │
│  ┌────────────────┐ ┌───────────────────┐ ┌───────────────────┐  │
│  │ Exposure       │ │ SurfaceBuilder    │ │ Analytics         │  │
│  │ Calculator     │ │ + MetricRegistry  │ │ Engine            │  │
│  └────────┬───────┘ └────────┬──────────┘ └────────┬──────────┘  │
├───────────┴──────────────────┴─────────────────────┴─────────────┤
│                 Data Normalization Layer                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐              │
│  │ StrikesFrame  │ │ MoniesFrame  │ │ SummaryRecord│              │
│  └──────┬────────┘ └──────┬───────┘ └──────┬───────┘             │
├─────────┴─────────────────┴────────────────┴─────────────────────┤
│                    Provider Layer                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  DataProvider (Protocol / ABC)                               │ │
│  │  ┌─────────────────┐  ┌─────────────────────────────────┐  │ │
│  │  │  OratsProvider   │  │  Future: IBKRProvider / CBOEProv│  │ │
│  │  └────────┬─────────┘  └─────────────────────────────────┘  │ │
│  └───────────┼─────────────────────────────────────────────────┘ │
├──────────────┼───────────────────────────────────────────────────┤
│              │  Infra Layer                                       │
│  ┌───────────┴───────┐  ┌─────────────┐  ┌───────────────────┐  │
│  │  CacheManager     │  │ RateLimiter  │  │ CircuitBreaker    │  │
│  │  (LRU + Redis +   │  │ (TokenBucket)│  │ (半开/全开/关闭)   │  │
│  │   Parquet)         │  │              │  │                   │  │
│  └───────────────────┘  └─────────────┘  └───────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 核心数据流

```
命令输入 → Regime 参数注入 (外部传入 iv30d/contango/vrp + ORATS 获取 iv_rank/iv_pctl/volOfVol)
         → Parameter Binding (校验 + 边界推导)
         → Targeted Data Fetch (API call, 精确过滤)
         → Computation (本地计算)
         → Render Output
```

---

## 4. Provider 层设计

### 4.1 DataProvider 抽象接口

```python
class DataProvider(Protocol):
    def get_strikes(self, ticker: str, dte: str = None,
                    delta: str = None, fields: list[str] = None) -> StrikesFrame: ...
    def get_monies(self, ticker: str, fields: list[str] = None) -> MoniesFrame: ...
    def get_summary(self, ticker: str) -> SummaryRecord: ...
    def get_ivrank(self, ticker: str) -> IVRankRecord: ...
    def get_hist_summary(self, ticker: str,
                         start_date: str, end_date: str) -> HistSummaryFrame: ...
```

### 4.2 OratsProvider 核心方法

| 方法 | 调用端点 | 请求参数策略 | 返回模型 |
|------|---------|-------------|---------|
| `get_strikes(ticker, dte?, delta?, fields?)` | `/datav2/strikes` | **必须指定 fields** 裁剪返回字段 | `StrikesFrame` |
| `get_monies(ticker, fields?)` | `/datav2/monies/implied` | 按需裁剪 fields | `MoniesFrame` |
| `get_summary(ticker)` | `/datav2/summaries` | 无过滤，单行返回 | `SummaryRecord` |
| `get_ivrank(ticker)` | `/datav2/ivrank` | 无过滤，单行返回 | `IVRankRecord` |
| `get_hist_summary(ticker, start, end)` | `/datav2/hist/summaries` | 按日期范围 | `HistSummaryFrame` |

### 4.3 字段裁剪策略

ORATS `/strikes` 端点默认返回 40+ 字段。按命令用途进行最小化裁剪：

| 命令用途 | fields 参数 | 预估行数压缩 |
|---------|------------|-------------|
| GEX 计算 | `tradeDate,expirDate,dte,strike,stockPrice,gamma,callOpenInterest,putOpenInterest,spotPrice` | ~800KB → ~150KB |
| DEX 计算 | 同上，`gamma` → `delta` | 同上 |
| VEX 计算 | 同上，`gamma` → `vega` | 同上 |
| Surface (IV) | `expirDate,dte,strike,callMidIv,putMidIv,smvVol,delta,spotPrice` | 同上 |
| OI 分布 | `expirDate,dte,strike,callOpenInterest,putOpenInterest,spotPrice` | ~100KB |

### 4.4 请求格式优化

对于高 OI 标的（SPX, SPY, QQQ），建议使用 CSV 格式请求以减少传输体积：

```
GET /datav2/strikes.csv?token=xxx&ticker=SPY&dte=0,60&fields=...
```

CSV 格式相比 JSON 可减少约 40% 的传输体积（无重复字段名）。

---

## 5. Regime-Aware 自适应边界

### 5.1 Regime 指标与输入方式

系统通过 6 个 regime 指标综合判定市场状态，进而驱动参数边界的自适应调整。其中 **iv30d、contango、vrp 由外部调用方传入**，**iv_rank、iv_pctl 和 volOfVol 由系统从 ORATS 获取**：

| 指标 | 定义 | 输入方式 |
|------|------|---------|
| **iv30d** | 30 天常数期限隐含波动率 | **外部参数传入** |
| **contango** | 期限升水/倒挂幅度 | **外部参数传入** |
| **vrp** | 波动率风险溢价 (IV - RV) | **外部参数传入** |
| **iv_rank** | IV Rank (0~100)，当前IV在52周极值区间中的线性位置 | ORATS `/ivrank` 端点 → `ivRank` 字段 |
| **iv_pctl** | IV Percentile (0~100)，过去N日中低于当前IV的百分比 | ORATS `/ivrank` 端点 → `ivPct` 字段 |
| **volOfVol** | 波动率的波动率 | ORATS `/summaries` → `volOfVol` 字段 |

#### 5.1.1 IVR 与 IVP 交叉验证

IV Rank 和 IV Percentile 衡量不同维度，单独使用会在特定场景下产生误判：

| | IV Rank (IVR) | IV Percentile (IVP) |
|---|---|---|
| 公式 | (当前IV - 52wk低) / (52wk高 - 52wk低) | 过去N日中低于当前IV的百分比 |
| 衡量的是 | 当前IV在极值区间中的线性位置 | 当前IV在历史分布中的概率位置 |
| 对尖峰的敏感度 | 极度敏感——一次 IV spike 会压低后续所有 IVR 读数 | 不敏感——一次 spike 只影响1个数据点 |
| 典型失真场景 | 曾有一次 IV spike 到 80%，当前30%，IVR=23%（"低位"）但实际已偏高 | 不受历史单次 spike 影响，IVP=85%（正确显示"高位"） |

系统将两者合成为两个派生指标：

```python
@property
def iv_consensus(self) -> float:
    """IVR 与 IVP 的加权共识值 (0~100)
    IVP 权重更高因为它对分布尖峰更鲁棒"""
    return 0.4 * self.iv_rank + 0.6 * self.iv_pctl

@property
def iv_divergence(self) -> float:
    """IVR 与 IVP 的分歧度 (0~100)
    高分歧意味着 IV 分布存在偏态，单一指标可能误导"""
    return abs(self.iv_rank - self.iv_pctl)
```

| 场景 | IVR | IVP | iv_consensus | iv_divergence | 意义 |
|------|-----|-----|-------------|---------------|------|
| 正常市场 | 45% | 50% | 48% | 5 | 一致，高置信度 |
| 财报后 IV crush（曾有spike） | 23% | 85% | 60% | 62 | **高分歧**——IVP 被 spike 后的区间压低修正 |
| 缓慢爬升到历史高位 | 88% | 82% | 84% | 6 | 一致，双确认 STRESS |
| Meme 股回落 | 15% | 40% | 30% | 25 | 中等分歧 |

### 5.2 Regime 三级分类

| 指标 | 低波 (LOW_VOL) | 正常 (NORMAL) | 压力 (STRESS) |
|------|----------------|--------------|---------------|
| iv30d | < 15% | 15-25% | > 25% |
| iv_consensus | < 30% | 30-70% | > 70% |
| contango | > +2 | -2 ~ +2 | < -2（倒挂） |
| volOfVol | 低 | 中 | 高 |
| vrp | 高正 | 适中 | 低/负 |

### 5.3 分类决策树

```
                    contango < -2 ?
                   /              \
                 YES               NO
                  │                 │
            ┌─────┴─────┐    iv30d > 25% AND iv_consensus > 70% ?
            │  STRESS   │         /              \
            │ (backwarda-│       YES               NO
            │  tion 是最 │        │                │
            │  强信号)   │   ┌────┴────┐    iv_consensus < 30% AND iv30d < 15% ?
            └───────────┘   │ STRESS   │         /              \
                            └──────────┘       YES               NO
                                                │                │
                                          ┌─────┴─────┐   ┌─────┴─────┐
                                          │  LOW_VOL   │   │  NORMAL   │
                                          └───────────┘   └───────────┘

附加规则: 当 iv_divergence > 30 时，regime 分类附加 confidence=LOW 标签
→ 边界推导公式中 sigma_multiplier 额外 ×1.1（安全加宽，因为分类置信度低）
```

**Backwardation 被赋予最高决策权重**——期限结构倒挂几乎总是伴随近端事件（财报、FOMC、黑天鹅），是最可靠的压力信号。

### 5.4 各指标的因果作用域

| 指标 | 驱动目标 | 因果可靠性 | 在架构中的角色 |
|------|---------|-----------|---------------|
| **iv30d** | strike window 宽度 | **强因果** — 直接从 BS 模型推导 | 核心输入，参与边界公式 |
| **iv_consensus** | strike window 修正系数 | **中等因果** — 交叉验证后的共识值比单一 IVP 更鲁棒 | 修正因子，±15~25% |
| **iv_divergence** | 分类置信度 / 安全边际 | **辅助因果** — 高分歧 = 低置信度 = 需要更保守的边界 | 修正因子，高分歧时加宽 10% |
| **contango** | dte window 重心 / 默认 dte | **强因果** — backwardation = 近端压力 | 核心输入，驱动 dte 默认值 |
| **volOfVol** | 缓存 TTL / 刷新频率 | **因果成立但作用域不同** | Infra 参数，不参与边界数值计算 |
| **vrp** | 输出上下文解读 | **弱因果** — 间接、滞后 | 上下文标注，附加在输出结果上 |

### 5.5 边界推导公式

```python
def compute_derived_boundaries(regime, context):

    # ── Strike Window ──
    
    # 基础: 覆盖 ±Nσ 的隐含波动范围，使用 iv_consensus 替代单一 ivpct
    if regime.iv_consensus > 70:
        sigma_multiplier = 2.5      # 高位 → 加宽（尾部暴露增加）
    elif regime.iv_consensus < 30:
        sigma_multiplier = 2.2      # 低位 → 略宽（IV 可能上升）
    else:
        sigma_multiplier = 2.0      # 正常

    # IVR 与 IVP 分歧度修正: 高分歧意味着分类不确定，需保守加宽
    if regime.iv_divergence > 30:
        sigma_multiplier *= 1.1     # 安全加宽 10%

    implied_move = context.spot_price * regime.iv30d * sqrt(default_dte / 365)
    strike_window_width = implied_move * sigma_multiplier
    default_strikes = ceil(strike_window_width / context.est_strike_step)
    default_strikes = clamp(default_strikes, min=8, max=30)     # 硬边界
    
    # ── DTE Window ──
    
    if regime.contango < -2:
        default_dte = 30            # backwardation → 聚焦近月
        dte_gravity = "near"
    elif regime.contango > +2:
        default_dte = 75            # 正常升水 → 适度放远
        dte_gravity = "far"
    else:
        default_dte = 60            # 平坦 → 标准
        dte_gravity = "balanced"

    # 财报感知: 如果窗口内有财报，扩展 dte 至少覆盖跨财报到期日
    if context.earnings.earnings_in_window:
        post_earn = find_first_expiry_after(context.earnings.next_date)
        default_dte = max(default_dte, post_earn.dte + 7)

    # ── Cache TTL ──
    
    if regime.vol_of_vol > 0.08:
        cache_ttl = 120             # 2 分钟（IV 快速变化）
    elif regime.vol_of_vol < 0.04:
        cache_ttl = 600             # 10 分钟（IV 稳定）
    else:
        cache_ttl = 300             # 5 分钟（标准）

    return DerivedBoundaries(
        default_strikes=default_strikes,
        default_dte=default_dte,
        strike_sigma_multiplier=sigma_multiplier,
        dte_gravity=dte_gravity,
        cache_ttl_seconds=cache_ttl,
        confidence="LOW" if regime.iv_divergence > 30 else "HIGH"
    )
```

### 5.6 数值示例

以 AAPL (spot=$218.50) 为例:

| Regime | iv30d | IVR | IVP | iv_consensus | iv_divergence | contango | default_strikes | default_dte |
|--------|-------|-----|-----|-------------|---------------|----------|-----------------|-------------|
| LOW_VOL | 12% | 18% | 22% | 20% | 4 | +3.5 | ≈ **10** | **75** |
| NORMAL | 22% | 48% | 52% | 50% | 4 | +1.0 | ≈ **14** | **60** |
| NORMAL (高分歧) | 22% | 23% | 78% | 56% | 55 | +1.0 | ≈ **16** (×1.1) | **60** |
| STRESS | 38% | 90% | 82% | 85% | 8 | -3.2 | ≈ **24** | **30** |

### 5.7 重要区分

| 概念 | 含义 | Regime 能驱动？ |
|------|------|---------------|
| **参数边界** (Parameter Boundary) | 查询数据时的 dte/strike/delta 过滤范围 | ✅ 能 |
| **微观结构边界** (Microstructure Boundary) | GEX flip point、gamma wall 等结构性价位 | ❌ 不能——这些是计算结果 |

Regime 信号决定**"用多大的望远镜去看"**，而不是**"看到了什么"**。

---

## 6. 计算层设计

### 6.1 模块结构

计算层按业务领域拆分为四个子包，每个文件控制在 200 行以内，单一职责：

```
compute/
├── __init__.py
├── exposure/                        # Greeks Exposure 计算
│   ├── __init__.py                  # 导出 ExposureCalculator
│   ├── calculator.py                # compute_exposure() 泛化引擎
│   ├── scaling.py                   # ScalingFn: GAMMA/DELTA/VEGA_EXPOSURE
│   └── models.py                    # ExposureFrame, SignConvention
│
├── volatility/                      # 波动率结构分析
│   ├── __init__.py                  # 导出所有 Builder
│   ├── registry.py                  # MetricDef + MetricRegistry (全局注册表)
│   ├── surface.py                   # SurfaceBuilder + IVSurfaceStrategy + GreekSurfaceStrategy
│   ├── term.py                      # TermBuilder (1D 期限结构)
│   ├── skew.py                      # SkewBuilder (2D skew 曲线, delta 坐标)
│   ├── smile.py                     # SmileBuilder (2D smile 曲线, strike 坐标)
│   └── models.py                    # SurfaceFrame, SkewFrame, TermFrame, SmileFrame
│
├── flow/                            # 资金流/持仓分析
│   ├── __init__.py
│   ├── max_pain.py                  # compute_max_pain()
│   ├── pcr.py                       # compute_pcr()
│   └── unusual.py                   # detect_unusual()
│
└── earnings/                        # 财报事件分析
    ├── __init__.py
    ├── implied_move.py              # compute_implied_move()
    └── iv_rank.py                   # compute_iv_rank()
```

模块间依赖关系：

```
exposure/calculator.py ◄── volatility/surface.py
│                            (GreekSurfaceStrategy 需要 compute_exposure()
│                             来计算 GEX/VEX/DEX surface)
│
volatility/registry.py ◄── volatility/surface.py
                        ◄── volatility/skew.py
                        ◄── volatility/smile.py
                        ◄── volatility/term.py
```

### 6.2 exposure/ — 泛化的暴露计算引擎

#### 6.2.1 GEX 计算公式

```
GEX_call_per_strike = gamma × callOI × 100 × spotPrice² × 0.01
GEX_put_per_strike  = gamma × putOI  × 100 × spotPrice² × 0.01 × (-1)
Net_GEX_per_strike  = GEX_call + GEX_put
```

#### 6.2.2 各 Greek 暴露差异

| | GEX | DEX | VEX |
|---|---|---|---|
| 使用的 Greek | gamma | delta | vega |
| 合约乘数 | × spotPrice² × 0.01 | × spotPrice × 1 | × 1 |
| Put 符号 | 取反 | 不取反（put delta 已为负） | 不取反（vega 同号） |

#### 6.2.3 泛化设计 (calculator.py)

```python
def compute_exposure(
    strikes_frame: StrikesFrame,
    greek: Literal["gamma", "delta", "vega"],
    scaling_fn: Callable[[float], float],
    sign_convention: SignConvention
) -> ExposureFrame:
    """所有 GEX/DEX/VEX 共享此方法"""
```

#### 6.2.4 缩放函数 (scaling.py)

```python
# 每种 Greek 暴露的缩放公式独立定义，新增 Greek 只需添加函数
GAMMA_EXPOSURE = lambda spot: spot ** 2 * 0.01 * 100
DELTA_EXPOSURE = lambda spot: spot * 100
VEGA_EXPOSURE  = lambda spot: 100  # vega 本身已是美元/vol点
```

#### 6.2.5 GEX 子命令差异

| 命令 | 语义 | 聚合方式 | 输出 |
|------|------|---------|------|
| `gexr` | GEX by Strike (Profile) | 按 strike 聚合所有到期日 | 柱状图: X=strike, Y=net GEX ($) |
| `gexn` | GEX Notional | 所有 strike + 所有到期日总和 | 单一数值 (如 "$+2.3B net gamma") |
| `gexs` | GEX by Expiry | 按 expirDate 聚合所有 strike | 柱状图: X=expirDate, Y=net GEX |

三个命令共享同一个 `compute_exposure()` 方法，仅最终 `groupby` 维度不同。

### 6.3 volatility/ — 波动率结构分析

#### 6.3.1 MetricRegistry (registry.py)

全局注册表，驱动 surface/skew/smile/term 的策略路由：

```python
MetricRegistry = {
    # ── IV Domain ──
    "iv":         MetricDef(source=MONIES, strategy=IVSurfaceStrategy,    z_label="IV %"),
    "smvVol":     MetricDef(source=MONIES, strategy=IVSurfaceStrategy,    z_label="SMV Vol %"),
    "ivask":      MetricDef(source=MONIES, strategy=IVSurfaceStrategy,    z_label="Ask IV %"),
    "calVol":     MetricDef(source=MONIES, strategy=IVSurfaceStrategy,    z_label="Calendar Vol"),
    "earnEffect": MetricDef(source=MONIES, strategy=IVSurfaceStrategy,    z_label="Earn Effect"),

    # ── Greeks Domain ──
    "gamma":  MetricDef(source=STRIKES, strategy=GreekSurfaceStrategy, z_label="Gamma",  scaling=RAW),
    "delta":  MetricDef(source=STRIKES, strategy=GreekSurfaceStrategy, z_label="Delta",  scaling=RAW),
    "vega":   MetricDef(source=STRIKES, strategy=GreekSurfaceStrategy, z_label="Vega",   scaling=RAW),
    "theta":  MetricDef(source=STRIKES, strategy=GreekSurfaceStrategy, z_label="Theta",  scaling=RAW),

    # ── Exposure Domain (Greeks × OI) ──
    "gex": MetricDef(source=STRIKES, strategy=GreekSurfaceStrategy, z_label="GEX $",
                     scaling=GAMMA_EXPOSURE, requires_oi=True),
    "vex": MetricDef(source=STRIKES, strategy=GreekSurfaceStrategy, z_label="VEX $",
                     scaling=VEGA_EXPOSURE,  requires_oi=True),
    "dex": MetricDef(source=STRIKES, strategy=GreekSurfaceStrategy, z_label="DEX $",
                     scaling=DELTA_EXPOSURE, requires_oi=True),
}
```

**新增 metric 只需注册一行**，无需修改 Strategy 代码——开闭原则的实践。

#### 6.3.2 SurfaceBuilder (surface.py)

统一入口，MetricRegistry 路由，统一输出格式：

```
surface <symbol> --metric iv
       │
       ▼
  SurfaceCommand (统一入口)
       │
       ▼
  MetricRegistry.lookup(metric)
       │
       ├──── metric ∈ IV Domain ────→ IVSurfaceStrategy
       │     数据源: /monies/implied      X轴: delta (0~100)
       │     直接读取 vol0~vol100          无需区分 call/put
       │
       └──── metric ∈ Greeks Domain ──→ GreekSurfaceStrategy
             数据源: /strikes              X轴: strike price
             需计算 exposure               必须区分 call/put
       │
       ▼
  SurfaceFrame (统一输出)
  {x_axis, y_axis, z_label, data, coord_type, contract_side}
```

#### 6.3.3 TermBuilder (term.py)

构建 1D 期限结构（ATM IV 按 DTE 排列）。

- 默认数据源: MoniesFrame 的 per-expiry `atmiv`
- 可选 overlay: SummaryRecord 的 `atmFcstIvM1~M4`（forecast 对比）
- 输出: TermFrame (DataFrame: dte, expir_date, atmiv, forecast_iv?)

#### 6.3.4 SkewBuilder (skew.py)

构建 2D IV 偏斜曲线（X=delta）。

- 数据源: MoniesFrame 的 `vol0~vol100`
- 支持 `--compare` 叠加多个到期日
- 输出: SkewFrame (DataFrame: delta, iv, expir_date)

#### 6.3.5 SmileBuilder (smile.py)

构建 2D IV 微笑曲线（X=strike price）。

- 数据源: StrikesFrame 的 `callMidIv, putMidIv, smvVol`
- 支持 `--overlay_smv` 叠加 SMV 拟合线
- 输出: SmileFrame (DataFrame: strike, call_iv, put_iv, smv_vol)

### 6.4 flow/ — 资金流/持仓分析

| 文件 | 方法 | 输入 | 输出 | 调用命令 |
|------|------|------|------|---------|
| max_pain.py | `compute_max_pain(strikes, spot)` | 单到期日 strikes | (max_pain_strike, pain_curve) | maxpain |
| pcr.py | `compute_pcr(summary)` | SummaryRecord | (vol_pcr, oi_pcr) | pcr, snap |
| unusual.py | `detect_unusual(strikes, thresholds)` | strikes + 阈值 | 异常行 DataFrame | unusual |

### 6.5 earnings/ — 财报事件分析

| 文件 | 方法 | 输入 | 输出 | 调用命令 |
|------|------|------|------|---------|
| implied_move.py | `compute_implied_move(strikes, spot)` | ATM strikes | implied_move_pct | ermv, snap |
| iv_rank.py | `compute_iv_rank(current_iv, hist_series, period)` | 标量 + 序列 | (rank, percentile) | ivrank, snap |

---

## 7. 命令层设计

### 7.1 命令全景

```
┌─────────────────────────────────────┐
│       Exposure 族                    │
│  gexr  gexn  gexs                   │
│  dex   dexn                          │
│  vex   vexn                          │
├─────────────────────────────────────┤
│       Surface / Structure 族         │
│  surface  skew  smile  term          │
├─────────────────────────────────────┤
│       OI / Flow 族                   │
│  pcr   oi   maxpain                  │
├─────────────────────────────────────┤
│       Volatility Analytics 族        │
│  ivrank  vvol  earn  ermv            │
├─────────────────────────────────────┤
│       Composite 族                   │
│  snap   unusual                      │
└─────────────────────────────────────┘
```

### 7.2 各命令详细规格

#### 7.2.1 Exposure 族

**`gexr` — GEX by Strike (Profile)**

```
gexr <symbol>
  --dte               DTE 上限（默认: regime-aware）
  --strikes           ATM 上下各 N 个 strike（默认: regime-aware）
  --expiration_filter  w|m|q|fd|all|next（默认: all）
```

- 数据源: `/strikes`
- 计算: gamma × OI × 100 × spotPrice² × 0.01, 按 strike 聚合
- 输出: 柱状图 X=strike, Y=net GEX($)

**`gexn` — GEX Notional**

```
gexn <symbol>
  --dte               DTE 上限（默认: regime-aware）
  --expiration_filter  w|m|q|fd|all|next（默认: all）
```

- 输出: 单一数值，如 "$+2.3B net gamma"

**`gexs` — GEX by Expiry**

```
gexs <symbol>
  --dte               DTE 上限（默认: regime-aware）
  --expiration_filter  w|m|q|fd|all（默认: all）
```

- 输出: 柱状图 X=expirDate, Y=net GEX

**`dex` / `dexn`** — 与 GEX 结构对称，使用 delta 替代 gamma，缩放公式不同。

**`vex` / `vexn`** — 与 GEX 结构对称，使用 vega 替代 gamma。

#### 7.2.2 Surface / Structure 族

**`surface` — 波动率/Greeks 曲面**

```
surface <symbol>
  --metric            iv|smvVol|ivask|calVol|gamma|delta|vega|gex|vex|dex（默认: iv）
  --dte               DTE 切片列表（默认: 7,14,30,60,90）
  --expiration_filter  w|m|q|all（默认: all）
  --contract_filter   calls|puts|all（仅 Greeks 域有效，默认: all）
  --strikes           ATM 上下 N 个 strike（仅 Greeks 域有效，默认: 20）
  --output            heatmap|contour|table（默认: heatmap）
```

当 metric 属于 IV 域时，`contract_filter` 和 `strikes` 参数静默忽略。

**`skew` — IV 偏斜曲线（delta 坐标）**

```
skew <symbol>
  --expiry            指定到期日或 DTE（默认: 30）
  --metric            iv|slope|deriv（默认: iv）
  --compare           对比另一个 DTE（如 skew AAPL --expiry 30 --compare 90）
```

- 数据源: `/monies/implied` 的 vol0~vol100
- X 轴: delta (0~100)

**`smile` — IV 微笑曲线（strike 坐标）**

```
smile <symbol>
  --expiry            指定到期日或 DTE（默认: nearest monthly）
  --contract_filter   calls|puts|mid（默认: mid=smvVol）
  --strikes           ATM 上下 N 个 strike（默认: 15）
  --overlay_smv       叠加 SMV 拟合线 vs raw IV
```

- 数据源: `/strikes` 的 callMidIv, putMidIv, smvVol
- X 轴: strike price

**`term` — 期限结构**

```
term <symbol>
  --max_dte           最远 DTE（默认: 180）
  --metric            atmiv|calVol|earnEffect（默认: atmiv）
  --overlay           forecast 叠加（对比 atmFcstIvM1~M4 vs 实际）
  --standard_only     仅标准月（M1~M4）
```

- 默认数据源: `/monies/implied` 的 per-expiry atmiv（全量到期日）
- `--standard_only`: 切换为 summaries 的 `atmIvM1~M4`（仅 4 点）

#### 7.2.3 OI / Flow 族

**`pcr` — Put/Call Ratio**

```
pcr <symbol>
  --basis             volume|oi|both（默认: both）
```

- 数据源: `/summaries` → cVolu, pVolu, cOi, pOi

**`oi` — Open Interest 分布**

```
oi <symbol>
  --dte               DTE 上限（默认: regime-aware）
  --expiration_filter  w|m|q|fd|all（默认: all）
  --strikes           ATM 上下 N 个 strike（默认: 20）
```

- 数据源: `/strikes` → callOpenInterest, putOpenInterest

**`maxpain` — 最大痛点**

```
maxpain <symbol>
  --expiry            指定到期日或 DTE（默认: next）
  --top_n             展示 Top N 候选（默认: 1）
```

- 数据源: `/strikes`（单到期日）
- 计算: O(strikes²)，对每个候选 strike 计算总内在价值

#### 7.2.4 Volatility Analytics 族

**`ivrank` — IV Rank / Percentile**

```
ivrank <symbol>
  --period            30|90|252|365（历史窗口，默认: 252）
  --metric            ivrank|ivpctl|both（默认: both）
```

- 数据源: `/ivrank` (直接读取) 或 `/hist/summaries` (精确自算)

**`vvol` — Volatility of Volatility**

```
vvol <symbol>
  --type              realized|implied|both（默认: both）
```

- 数据源: `/summaries` → volOfVol, volOfIvol

**`earn` — 财报日历与隐含波动**

```
earn <symbol>
```

- 输出: 下次财报日期、隐含财报移动、earn effect 在 term structure 上的凸起

**`ermv` — Implied Earnings Move**

```
ermv <symbol>
  --history           展示历史实际 vs 隐含 move 对比
```

- 数据源: summaries + (可选) hist/summaries

#### 7.2.5 Composite 族

**`snap` — 标的快照（编排命令）**

```
snap <symbol>
```

- 输出: spot price, ATM IV, IV rank, PCR, net GEX, vvol, 下次财报, regime 分类
- 实现: 调用已有的 `compute_gex_notional()`, `compute_pcr()`, `read_vvol()` 等方法
- **不编写独立计算逻辑，验证架构"高内聚低耦合"的试金石**

**`unusual` — 异常 OI/Volume 检测**

```
unusual <symbol>
  --min_volume        最小 volume 阈值（默认: 1000）
  --min_oi            最小 OI 阈值（默认: 500）
  --vol_oi_ratio      Volume/OI 比率阈值（默认: 2.0）
  --dte               DTE 上限（默认: 60）
```

- 数据源: `/strikes`

---

## 8. 统一参数体系

### 8.1 全局参数语义

| 参数名 | 类型 | 语义 | 适用命令 | 默认值策略 |
|--------|------|------|---------|-----------|
| `symbol` | str (必填) | 标的 ticker | 全部 | — |
| `dte` | int 或 int,int | 最大 DTE 或 DTE 范围 | 全部 | regime-aware (30/60/75) |
| `expiration_filter` | enum | w/m/q/fd/all/next | Exposure + OI 族 | all |
| `strikes` | int | ATM 上下各 N 个 strike | Exposure + OI 族 | regime-aware (8~30) |
| `metric` | enum | 度量指标 | surface/skew/term | 命令默认 |
| `contract_filter` | enum | calls/puts/all/itm/otm/ntm | surface(Greeks)/smile | all |
| `expiry` | date 或 int | 指定到期日或 DTE | skew/smile/maxpain | nearest monthly |
| `output` | enum | 输出格式 | surface | heatmap |

### 8.2 参数联动规则

- 当 `surface --metric` 属于 IV 域时，`contract_filter` 和 `strikes` 静默忽略
- 当 `maxpain --expiry` 传入 DTE 值时，自动映射到最近到期日
- 当用户未显式指定 dte/strikes 时，使用 regime-aware 计算的默认值

---

## 9. 缓存与基础设施设计

### 9.1 缓存分层

| 缓存层 | 存储介质 | 适用数据 | TTL 策略 |
|--------|---------|---------|---------|
| L1: 进程内 LRU | Python `functools.lru_cache` | SummaryRecord, IVRankRecord（小、高频） | Regime-aware: 2~10 分钟 |
| L2: Redis | Redis | StrikesFrame, MoniesFrame（大、共享） | Regime-aware: 2~10 分钟 |
| L3: 本地 Parquet | 文件系统 | HistSummaryFrame（不可变历史数据） | 永不过期，每日增量追加 |

### 9.2 缓存键设计

```
Cache Key = f"{ticker}:{endpoint}:{fields_hash}:{filter_hash}"

示例:
  "AAPL:strikes:a3f2b1:dte0-60_delta0.12-0.88"
  "AAPL:monies:full:no_filter"
  "AAPL:summary:full:no_filter"
```

### 9.3 容灾降级

| 场景 | 行为 |
|------|------|
| ORATS API 超时 / 5xx | 返回最近缓存数据 + 标注 `stale=True` |
| 缓存数据超过 1 小时 | 拒绝返回，明确告知用户数据不可靠 |
| 单标的请求失败 | 不影响其他标的的请求（熔断隔离） |

### 9.4 限流设计

ORATS API 限制 1000 req/min。系统内实现令牌桶限流：

```
Token Bucket:
  capacity: 800 tokens (留 20% 安全余量)
  refill_rate: 800 / 60 ≈ 13.3 tokens/sec
  per_request_cost: 1 token
```

---

## 10. 数据流汇总

### 10.1 命令 → 端点映射矩阵

| 命令 | get_strikes | get_monies | get_summary | get_ivrank | get_hist_summary | 调用频次 |
|------|:-----------:|:----------:|:-----------:|:----------:|:----------------:|:--------:|
| gexr | ✅ | | ✅ | | | 高 |
| gexn | ✅ | | ✅ | | | 高 |
| gexs | ✅ | | ✅ | | | 中 |
| dex/dexn | ✅ | | ✅ | | | 中 |
| vex/vexn | ✅ | | ✅ | | | 中 |
| skew | | ✅ | | | | 高 |
| surface (IV) | | ✅ | | | | 中 |
| surface (Greek) | ✅ | | ✅ | | | 中 |
| term | | ✅ | ✅ | | | 中 |
| smile | ✅ | | | | | 中 |
| pcr | | | ✅ | | | 高 |
| oi | ✅ | | | | | 高 |
| maxpain | ✅ | | | | | 中 |
| ivrank | | | ✅ | ✅ | ✅ | 高 |
| vvol | | | ✅ | | | 中 |
| earn/ermv | | | ✅ | | ✅(可选) | 中 |
| snap | ✅(小范围) | | ✅ | ✅ | | 高 |
| unusual | ✅ | | | | | 中 |

### 10.2 端到端调用链示例

```
gexr AAPL  (regime 参数由外部注入: iv30d=21.5%, contango=+1.8, vrp=+3.2%)
  │
  ├─→ 获取 ORATS 侧 regime 指标:
  │     ├─→ get_ivrank("AAPL")         → ivRank=48%, ivPct=52%        [API #1]
  │     └─→ get_summary("AAPL")        → volOfVol=0.05, spot=218.50   [API #2]
  │
  ├─→ 组装完整 regime:
  │     {iv30d: 21.5%, iv_rank: 48%, iv_pctl: 52%,
  │      iv_consensus: 50%, iv_divergence: 4,
  │      contango: +1.8, volOfVol: 0.05, vrp: +3.2%}
  │     → 分类: NORMAL (confidence=HIGH, divergence < 30)
  │     → 推导边界: default_strikes=14, default_dte=60, cache_ttl=300s
  │
  ├─→ ParamResolver.bind(RawParams{dte=None, strikes=None}, regime_boundaries)
  │     → dte=60, strikes=14, delta_range=(0.15, 0.85)
  │
  ├─→ Provider.get_strikes("AAPL", dte="0,60",
  │     delta="0.15,0.85", fields=[...])                              [API #3]
  │     → ~200 行 (vs 无过滤 2000+)
  │
  ├─→ 本地过滤 + 裁剪: spot 为中心 ±14 strikes
  ├─→ ExposureCalculator.compute_gex(filtered_strikes)
  │
  └─→ Renderer.render(gex_profile, regime_context={
        regime_class: "NORMAL", confidence: "HIGH",
        iv30d: 21.5%, iv_rank: 48%, iv_pctl: 52%,
        contango: +1.8, vrp: +3.2%
      })
```

**总计 3 次 API 调用（首次）；后续同 ticker 命令因 summary/ivrank 缓存可降至 1 次。**

---

## 11. 风险与权衡

| 风险点 | 影响等级 | 缓解策略 |
|--------|---------|---------|
| ORATS 未公开精确 rate limit 行为 | 中 | 令牌桶限流 ≤800 req/min；fields 裁剪减少 payload |
| SPX/SPY strikes 数据量巨大 (3000+行) | 高 | 服务端 dte/delta 过滤；CSV 格式；字段裁剪 |
| monies/implied 不覆盖 0DTE 到期日 | 中 | 对 0DTE fallback 到 /strikes 逐 strike 计算 |
| 15 分钟延迟在快速行情中失真 | 中 | 输出标注数据时间戳；Live API 作为升级路径 |
| GEX 计算公式行业变体不统一 | 中 | 文档明确公式；可配置 spotgamma/tradytics 变体 |
| 高 IV 环境 delta 分布压缩 | 中 | IV-aware 修正: atm_iv > 0.80 时加宽 delta range |

---

## 12. 实施优先级

### 12.1 分阶段交付

| 阶段 | 范围 | 理由 |
|------|------|------|
| **P0 — 基础设施** | Provider 层 + 缓存框架 + Regime 参数接口 | 所有命令的地基 |
| **P0 — 核心命令** | gexr, gexn, gexs, dex, dexn, vex, vexn | 主要价值交付 |
| **P0 — 同批交付** | pcr, oi | 零额外开发成本，完全复用已有调用 |
| **P1 — 紧随其后** | surface, skew, term, snap, maxpain, smile | snap 是架构验证的试金石 |
| **P2 — 需要 hist 端点** | ivrank, earn, ermv | 新增 get_hist_summary() + Parquet 缓存 |
| **P3 — 锦上添花** | vvol, unusual | 有价值但频率较低 |

### 12.2 依赖关系

```
Provider 层 + Regime 接口 ──→ 所有命令
              │
       Regime 参数绑定
              │
       ┌──────┴───────┐
       ▼               ▼
  P0 命令族        P1 命令族
  (Exposure)       (Surface/Analytics)
                        │
                        ▼
                  P2 命令族
                  (需 hist 端点)
```

---

## 13. 附录

### 13.1 ORATS API 核心端点速查

| 端点 | 方法 | 必填参数 | 可选参数 | 返回格式 |
|------|------|---------|---------|---------|
| `/datav2/strikes` | GET | ticker | fields, dte, delta | JSON / CSV |
| `/datav2/monies/implied` | GET | ticker | fields | JSON / CSV |
| `/datav2/summaries` | GET | ticker | fields | JSON / CSV |
| `/datav2/ivrank` | GET | ticker | fields | JSON / CSV |
| `/datav2/hist/strikes` | GET | ticker, tradeDate | fields, dte, delta | JSON / CSV |
| `/datav2/hist/summaries` | GET | ticker, tradeDate | fields | JSON / CSV |
| `/datav2/tickers` | GET | (none) | ticker | JSON / CSV |

### 13.2 ORATS Strikes 端点关键字段清单

```
ticker, tradeDate, expirDate, dte, strike, stockPrice,
callVolume, callOpenInterest, callBidSize, callAskSize,
putVolume, putOpenInterest, putBidSize, putAskSize,
callBidPrice, callValue, callAskPrice,
putBidPrice, putValue, putAskPrice,
callBidIv, callMidIv, callAskIv,
smvVol,
putBidIv, putMidIv, putAskIv,
residualRate, delta, gamma, theta, vega, rho, phi,
driftlessTheta, extSmvVol, extCallValue, extPutValue,
spotPrice, updatedAt
```

### 13.3 ORATS Monies/Implied 端点关键字段清单

```
ticker, tradeDate, expirDate, stockPrice,
riskFreeRate, yieldRate, residualYieldRate,
residualRateSlp, residualR2, confidence, mwVol,
vol100, vol95, vol90, vol85, vol80, vol75, vol70,
vol65, vol60, vol55, vol50, vol45, vol40, vol35,
vol30, vol25, vol20, vol15, vol10, vol5, vol0,
atmiv, slope, deriv, fit, spotPrice,
calVol, unadjVol, earnEffect, updatedAt
```

### 13.4 ORATS Summaries 端点关键字段清单

```
ticker, tradeDate, assetType, priorCls, pxAtmIv, mktCap,
cVolu, cOi, pVolu, pOi,
orFcst20d, orIvFcst20d, orFcstInf, orIvXern20d, orIvXernInf,
iv200Ma,
atmIvM1, atmFitIvM1, atmFcstIvM1, dtExM1,
atmIvM2, atmFitIvM2, atmFcstIvM2, dtExM2,
atmIvM3, atmFitIvM3, atmFcstIvM3, dtExM3,
atmIvM4, atmFitIvM4, atmFcstIvM4, dtExM4,
iRate5wk, iRateLt, px1kGam, volOfVol, volOfIvol,
slope, slopeInf, slopeFcst, slopeFcstInf,
deriv, derivInf, derivFcst, derivFcstInf,
mktWidthVol, mktWidthVolInf,
ivEarnReturn, fcstR2, fcstR2Imp,
stkVolu, avgOptVolu20d
```

### 13.5 隐含波动范围公式

```python
implied_1sigma_move = spot_price * iv30d * sqrt(dte / 365)

# 示例 (AAPL spot=218.50, iv30d=22%, dte=30):
# 218.50 × 0.22 × √(30/365) = $13.77
# → 1σ 范围: $204.73 ~ $232.27
```

---

> **文档结束**  
> 本设计方案基于 ORATS Delayed Data API v2 编写，API 行为以 ORATS 官方文档为准。
