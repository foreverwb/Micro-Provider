# Provider 开发任务指令 v1.2

> **使用方式**: 将本文件完整内容作为首条 user message 发送给 Opus，
> 同时上传 `provider-design.md` 作为附件。
> 每个 Phase 完成后回复"继续下一阶段"推进。

---

## 角色

你是一位精通期权微观结构与 Python 高可用系统架构的资深量化开发工程师。
你将根据附件中的详细设计方案（provider-design.md），
逐阶段实现一套完整的 Options Microstructure Data Provider 服务。

## 背景

本项目为构建数据后端，依赖 ORATS Delayed Data API 提供
期权 Greeks Exposure（GEX/DEX/VEX）与 Volatility Structure（Skew/Surface/Term）
的计算服务。设计文档已经过完整评审，请严格遵循。

## 技术栈约束

- Python 3.11+
- HTTP 客户端: httpx (async)
- 数据模型: Pydantic v2 (BaseModel + model_validator)
- 数据处理: pandas（StrikesFrame/MoniesFrame 内部用 DataFrame 承载）
- 缓存: functools.lru_cache (L1) + 可选 Redis (L2) + Parquet (L3 hist)
- 测试: pytest + pytest-asyncio
- 无外部框架依赖（不引入 FastAPI/Flask，Provider 是纯库）

## 代码规范 — 注释要求

**所有输出代码必须包含充分的注释。** 具体要求如下：

1. **模块级 docstring**: 每个 `.py` 文件顶部必须有模块 docstring，
   说明该模块的职责、在架构中的位置、以及与哪些模块有依赖关系。
   示例:
   ```python
   """
   exposure/calculator.py — 泛化的 Greeks Exposure 计算引擎

   职责: 提供 compute_exposure() 方法，支持 GEX/DEX/VEX 三种暴露计算。
   所有暴露计算共享此入口，通过 scaling_fn 和 sign_convention 参数区分。

   依赖: exposure.scaling (缩放函数), exposure.models (ExposureFrame)
   被依赖: volatility.surface (GreekSurfaceStrategy 调用 compute_exposure)
   """
   ```

2. **类级 docstring**: 每个 class 必须有 docstring，说明该类的作用和核心属性。

3. **方法级 docstring**: 每个 public 方法必须有 docstring，包含:
   - 一句话功能描述
   - Args 说明（含类型和含义）
   - Returns 说明
   - 涉及金融逻辑的方法须注明公式来源或计算依据

4. **行内注释**: 在以下场景**必须**添加行内注释:
   - 金融计算公式（如 GEX = gamma × OI × 100 × spot² × 0.01）
   - 业务规则分支（如 put 符号取反的原因）
   - 非显而易见的数据转换（如 delta range 到 strike range 的近似映射）
   - 缓存策略的 TTL 选择依据
   - 常量/魔数的含义

5. **不要过度注释**: 自描述代码（如 `total = a + b`）不需要注释。
   注释应解释 **why** 而非 **what**。

## 项目目录结构

```
Micro_provider/
├── __init__.py
├── provider/
│   ├── __init__.py
│   ├── protocol.py            # DataProvider Protocol 抽象接口
│   ├── orats.py               # OratsProvider 实现
│   └── models.py              # StrikesFrame, MoniesFrame, SummaryRecord, IVRankRecord
│
├── compute/
│   ├── __init__.py
│   ├── exposure/              # Greeks Exposure 计算
│   │   ├── __init__.py        # 导出 ExposureCalculator, compute_gex/dex/vex
│   │   ├── calculator.py      # compute_exposure() 泛化引擎
│   │   ├── scaling.py         # ScalingFn: GAMMA/DELTA/VEGA_EXPOSURE
│   │   └── models.py          # ExposureFrame, SignConvention
│   │
│   ├── volatility/            # 波动率结构分析
│   │   ├── __init__.py        # 导出所有 Builder
│   │   ├── registry.py        # MetricDef + MetricRegistry 全局注册表
│   │   ├── surface.py         # SurfaceBuilder + IVSurfaceStrategy + GreekSurfaceStrategy
│   │   ├── term.py            # TermBuilder (1D 期限结构)
│   │   ├── skew.py            # SkewBuilder (2D skew 曲线, delta 坐标)
│   │   ├── smile.py           # SmileBuilder (2D smile 曲线, strike 坐标)
│   │   └── models.py          # SurfaceFrame, SkewFrame, TermFrame, SmileFrame
│   │
│   ├── flow/                  # 资金流/持仓分析
│   │   ├── __init__.py
│   │   ├── max_pain.py        # compute_max_pain()
│   │   ├── pcr.py             # compute_pcr()
│   │   └── unusual.py         # detect_unusual()
│   │
│   └── earnings/              # 财报事件分析
│       ├── __init__.py
│       ├── implied_move.py    # compute_implied_move()
│       └── iv_rank.py         # compute_iv_rank()
│
├── regime/
│   ├── __init__.py
│   └── boundary.py            # MarketRegime, DerivedBoundaries, classify()
│
├── commands/
│   ├── __init__.py
│   └── (后续阶段填充)
│
├── infra/
│   ├── __init__.py
│   ├── cache.py               # CacheManager (L1 LRU + L2 Redis接口)
│   └── rate_limiter.py        # TokenBucket
│
└── tests/
    ├── conftest.py            # ORATS mock fixtures
    ├── test_provider.py
    ├── test_exposure.py
    ├── test_volatility.py
    ├── test_regime.py
    └── test_flow.py
```

---

## 实施计划 — 请按阶段顺序执行

### Phase 0: 项目骨架与 Provider 层

1. **初始化项目结构**: 按上方目录创建所有 `__init__.py` 和空文件骨架。

2. **实现 `provider/protocol.py`**:
   - 定义 DataProvider Protocol（见设计文档 §4.1）
   - 5 个方法签名: get_strikes, get_monies, get_summary, get_ivrank, get_hist_summary
   - 每个方法须有完整的 docstring 说明参数和返回值

3. **实现 `provider/models.py`**:
   - StrikesFrame: Pydantic BaseModel 包装 pandas DataFrame，
     字段校验确保必要列存在（gamma/delta/vega, OI, strike, spotPrice 等）
   - MoniesFrame: 同上，校验 vol0~vol100, atmiv, slope, deriv 列存在
   - SummaryRecord: 平铺的 Pydantic model，
     包含设计文档 §13.4 列出的所有字段
   - IVRankRecord: 包含 ivRank 和 ivPct 两个字段（注意：两者都需要，
     用于 regime 模块的 IVR+IVP 交叉验证）
   - 所有 model 须有类级 docstring 和字段级注释

4. **实现 `provider/orats.py`**:
   - OratsProvider 类，实现 DataProvider Protocol
   - 构造函数接收: api_token, base_url, httpx.AsyncClient
   - 所有方法内部:
     a. 按设计文档 §4.3 裁剪 fields 参数（注释说明为何选择这些字段）
     b. 支持 JSON 和 CSV 两种返回格式（CSV 用 pandas.read_csv 解析）
     c. 统一错误处理（HTTP 错误 → 自定义异常）
   - **关键**: get_strikes 必须支持 dte 和 delta range 过滤参数
   - get_ivrank 必须返回同时包含 ivRank 和 ivPct 的 IVRankRecord

5. **实现 `infra/rate_limiter.py`**:
   - TokenBucket: capacity=800, refill_rate=13.3/sec
   - async acquire() 方法
   - 注释说明为何 capacity=800 而非 1000（留 20% 安全余量）

6. **实现 `infra/cache.py`**:
   - CacheManager: 键格式 = `{ticker}:{endpoint}:{fields_hash}:{filter_hash}`
   - L1: 进程内 dict + TTL
   - set_ttl() 方法支持 regime-aware 动态 TTL
   - stale 数据降级返回机制（注释标注 stale 阈值为何设为 1 小时）

### Phase 1: Regime 模块

7. **实现 `regime/boundary.py`**:
   - MarketRegime dataclass，包含 6 个字段:
     ```python
     iv30d: float       # 外部传入
     contango: float    # 外部传入
     vrp: float         # 外部传入
     iv_rank: float     # ORATS /ivrank → ivRank (0~100)
     iv_pctl: float     # ORATS /ivrank → ivPct (0~100)
     vol_of_vol: float  # ORATS /summaries → volOfVol
     ```
   - iv_consensus property: `0.4 * iv_rank + 0.6 * iv_pctl`
     （注释说明权重选择: IVP 权重更高因为对分布尖峰更鲁棒）
   - iv_divergence property: `abs(iv_rank - iv_pctl)`
     （注释说明高分歧的金融含义: IV 分布存在偏态或历史 spike）
   - classify(regime) → LOW_VOL | NORMAL | STRESS
     按设计文档 §5.3 的决策树实现，包含 confidence 标签:
     - iv_divergence > 30 → confidence=LOW
     - 否则 → confidence=HIGH
   - compute_derived_boundaries(regime, spot_price, est_strike_step)
     → DerivedBoundaries(default_strikes, default_dte,
        sigma_multiplier, dte_gravity, cache_ttl, confidence)
     公式严格按设计文档 §5.5，包含:
     - iv_consensus 驱动 sigma_multiplier（注释公式含义）
     - iv_divergence > 30 时 sigma_multiplier × 1.1（注释安全加宽原因）
     - contango 驱动 dte_gravity（注释 backwardation 的金融含义）
     - volOfVol 驱动 cache_ttl（注释为何不参与边界数值计算）

### Phase 2: 计算层 — exposure/

8. **实现 `compute/exposure/models.py`**:
   - SignConvention 枚举: NEGATE_PUT, KEEP_SIGN
     （注释说明: gamma 暴露中 put 侧取反因为 put gamma 的方向效应相反）
   - ExposureFrame: 包含 DataFrame 的 wrapper
     - 验证必须包含 exposure_value 列

9. **实现 `compute/exposure/scaling.py`**:
   - GAMMA_EXPOSURE: `lambda spot: spot ** 2 * 0.01 * 100`
   - DELTA_EXPOSURE: `lambda spot: spot * 100`
   - VEGA_EXPOSURE: `lambda spot: 100`
   - 每个 lambda 上方有注释说明物理含义和量纲

10. **实现 `compute/exposure/calculator.py`**:
    - compute_exposure() 泛化方法（设计文档 §6.2.3）
    - 快捷方法: compute_gex(), compute_dex(), compute_vex()
      各自调用 compute_exposure() 并传入对应 scaling + sign_convention
    - 行内注释标注 GEX 公式的每一步计算

### Phase 3: 计算层 — volatility/

11. **实现 `compute/volatility/models.py`**:
    - SurfaceFrame: x_axis, y_axis, z_label, data(DataFrame), coord_type
    - SkewFrame: DataFrame wrapper (delta, iv, expir_date)
    - TermFrame: DataFrame wrapper (dte, expir_date, atmiv)
    - SmileFrame: DataFrame wrapper (strike, call_iv, put_iv, smv_vol)

12. **实现 `compute/volatility/registry.py`**:
    - MetricDef dataclass: source, strategy_class, z_label, scaling, requires_oi
    - MetricRegistry: 字典，完整注册设计文档 §6.3.1 中所有 metric
    - lookup() 方法，返回 MetricDef 或抛出 UnknownMetricError

13. **实现 `compute/volatility/surface.py`**:
    - SurfaceBuilder.build(metric, data) → SurfaceFrame
    - IVSurfaceStrategy: 从 MoniesFrame 的 vol0~vol100 构建二维矩阵
      （注释: X=delta 0~100, Y=dte, Z=iv_value）
    - GreekSurfaceStrategy: 从 StrikesFrame 构建矩阵，
      若 requires_oi=True 则调用 exposure.calculator.compute_exposure()
      （注释: X=strike, Y=dte, Z=greek_or_exposure_value）

14. **实现 `compute/volatility/term.py`**:
    - TermBuilder.build(monies_frame, summary_record?, metric) → TermFrame
    - 默认从 MoniesFrame per-expiry atmiv 构建
    - overlay=True 时叠加 SummaryRecord 的 atmFcstIvM1~M4
    - 注释说明 term structure 的金融含义

15. **实现 `compute/volatility/skew.py`**:
    - SkewBuilder.build(monies_frame, expiry_or_dte, metric) → SkewFrame
    - 从 vol0~vol100 提取指定到期日的 delta 切片
    - 支持 compare 叠加多个到期日
    - 注释说明 skew 与 smile 的区别（坐标系不同）

16. **实现 `compute/volatility/smile.py`**:
    - SmileBuilder.build(strikes_frame, expiry, contract_filter) → SmileFrame
    - 从 strikes 的 callMidIv/putMidIv/smvVol 构建
    - 支持 overlay_smv 叠加 SMV 拟合线
    - 注释说明 smile 以 strike 为 X 轴而非 delta

### Phase 4: 计算层 — flow/ + earnings/

17. **实现 `compute/flow/max_pain.py`**:
    - compute_max_pain(strikes_df, spot_price) → (strike, pain_curve_df)
    - 注释说明 max pain 的计算逻辑: 对每个候选 strike 计算
      所有 call OI 和 put OI 的总内在价值

18. **实现 `compute/flow/pcr.py`**:
    - compute_pcr(summary) → (vol_pcr, oi_pcr)

19. **实现 `compute/flow/unusual.py`**:
    - detect_unusual(strikes_df, thresholds) → filtered_df
    - thresholds 为 Pydantic model 包含 min_volume, min_oi, vol_oi_ratio

20. **实现 `compute/earnings/implied_move.py`**:
    - compute_implied_move(strikes_df, spot_price) → float
    - 注释说明公式: ≈ ATM_straddle / spot × 100%

21. **实现 `compute/earnings/iv_rank.py`**:
    - compute_iv_rank(current_iv, hist_iv_series, period) → (rank, percentile)
    - 注释说明 IVR 与 IVP 的公式差异

### Phase 5: 集成测试

22. **编写 tests/conftest.py**:
    - Mock ORATS API 响应 fixture（用真实 AAPL 数据结构，造假数值）
    - 提供 mock_orats_provider fixture
    - Mock IVRankRecord 必须同时包含 ivRank 和 ivPct 字段

23. **测试覆盖**:
    - test_provider.py: OratsProvider 的 5 个方法 + 字段裁剪 + 错误处理
    - test_exposure.py: GEX/DEX/VEX 计算正确性 + put 符号 + 聚合维度
    - test_volatility.py:
      - MetricRegistry 路由: IV 域 vs Greeks 域正确分发
      - TermBuilder: 1D 期限结构构建
      - SkewBuilder: delta 坐标切片
      - SmileBuilder: strike 坐标切片
    - test_regime.py:
      - 三级分类正确性
      - iv_consensus 和 iv_divergence 计算
      - **用设计文档 §5.6 的四组数值示例作为 test case**
        （LOW_VOL / NORMAL / NORMAL高分歧 / STRESS）
      - 高分歧时 sigma_multiplier ×1.1 的验证
      - confidence 标签的正确设置
    - test_flow.py: max_pain 计算 + pcr 计算

---

## 关键约束 — 必须遵守

1. **CLI 和 API 共享同一计算路径**: commands/ 中的任何命令函数必须调用
   compute/ 中的方法，禁止在 commands/ 中重新实现计算逻辑。

2. **网络请求最小化**: get_strikes 调用必须传入 fields 参数，
   禁止获取全量字段。

3. **MetricRegistry 驱动**: 新增 metric 不允许修改 Strategy 类，
   只允许在 Registry 字典中添加一行。

4. **Provider 可替换**: OratsProvider 之外的所有代码不允许
   出现 "orats" 字符串或 ORATS 端点 URL。

5. **compute/ 模块边界**: exposure/ 内的代码不允许 import volatility/，
   但 volatility/ 可以 import exposure/（单向依赖）。
   flow/ 和 earnings/ 不依赖 exposure/ 或 volatility/。

6. **单文件不超过 250 行**: 如果任何文件超过此限制，
   必须拆分并说明原因。

7. **注释覆盖**: 所有金融计算公式、业务规则分支、
   缓存策略决策点必须有行内注释。
   模块/类/公共方法必须有 docstring。

---

## 输出要求

每个 Phase 完成后:
1. 输出该阶段的所有文件完整代码（含注释）
2. 列出该阶段新增的文件清单
3. 说明与下一阶段的接口契约
4. 标注任何偏离设计文档的决策及理由

从 Phase 0 开始。
