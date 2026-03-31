#Options Microstructure Provider

基于 ORATS API 的期权 Greeks Exposure 与波动率结构数据服务（Python 纯库）。

## Tech Stack

Python 3.11+, httpx (async), Pydantic v2, pandas, pytest

## 详细设计文档

完整的架构设计、命令规格、数据流、公式定义均在以下文件中，
实现前务必先读取对应章节：

- 设计方案: docs/provider-design.md
- 开发指令: docs/dev-instructions.md

## Build & Test
```bash
pip install -e ".[dev]"
pytest tests/ -v
pytest tests/test_exposure.py -v  # 单模块测试
```

## 代码规范

- 模块/类/公共方法必须有 docstring
- 金融计算公式必须有行内注释说明 why
- 单文件不超过 250 行，超过则拆分
- Provider 可替换: OratsProvider 之外的代码禁止出现 "orats" 字符串或 ORATS URL
- MetricRegistry 驱动: 新增 metric 只改 registry.py，不改 Strategy 类
- compute/ 内单向依赖: exposure/ 不 import volatility/，反向可以

## 目录结构
```
Micro-Provider/
├── provider/          # 数据获取 (DataProvider Protocol + OratsProvider)
├── compute/
│   ├── exposure/      # GEX/DEX/VEX 暴露计算
│   ├── volatility/    # Surface/Term/Skew/Smile
│   ├── flow/          # max_pain, pcr, unusual
│   └── earnings/      # implied_move, iv_rank
├── regime/            # 市场状态分类 + 边界推导
├── infra/             # 缓存 (LRU+Redis) + 限流 (TokenBucket)
├── commands/          # CLI 命令入口
└── tests/
```