# Trident Demo Runtime / Experiment Refactor Plan

本文档定义当前 demo 的分层改造方案。目标是把真实线上 Redis 流式处理链路从实验分析链路中拆出来，同时保留现有 demo、benchmark、可视化和压测能力。

## 1. 当前问题

当前 `TridentStreamingExperiment` 同时承担了四类职责：

- 输入读取：CSV、Redis Stream、Redis List。
- 线上处理：预处理、特征矩阵、初始化学习器、窗口推理、未知聚类、增量训练。
- 实验处理：年份/攻击类型过滤、攻击采样、标签分布、风险统计、overlap 聚合。
- 导出分析：dataset topology、learner topology、metric audit、decision tree、benchmark 报告。

这导致两个问题：

- 线上链路很难判断哪些步骤是部署必须的，哪些只是实验分析。
- Redis 流式 benchmark 中的耗时口径容易混入实验导出、采样和统计成本。

## 2. 改造目标

最终目标结构：

```text
trident_demo/
  runtime/        # 线上流式处理：输入、预处理、特征矩阵、online runner
  pipeline/       # 现有实验 pipeline，作为兼容层继续保留
  experiment/     # 后续迁移目标：实验分析、画像、可视化、benchmark 汇总
  core/           # TSieve / TMagnifier / TScissors
  io/             # Redis / CSV 输入适配
  export/         # 实验导出
```

本次第一阶段只做可落地的最小拆分：

- 新增 `runtime/` 子包。
- 新增 `online` CLI 入口。
- `runtime` 只负责 Redis 在线流式运行的配置裁剪和运行入口。
- 新增纯 runtime 预处理模块，明确哪些预处理属于线上必需。
- 保留旧 `run --profile ...` 入口不变。

## 3. 分层边界

### 3.1 Runtime 层

Runtime 只允许包含线上处理必须逻辑：

- Redis 输入读取。
- 字段标准化之后的 DataFrame 清洗。
- `Label` / `Timestamp` 缺省补齐。
- 时间解析、排序。
- `LabelNorm` 生成。
- 缺失值策略。
- 全零规则过滤。
- 数值特征选择。
- 固定特征列对齐。
- `float32` 特征矩阵输出。
- 在线运行配置：`perf_mode=true`、关闭重导出、禁用注入。

Runtime 不应该包含：

- 攻击类别采样。
- 年份过滤。
- 实验用 attack include / exclude。
- dataset topology。
- learner topology。
- metric audit。
- decision tree。
- overlap 聚合。
- 依赖当前整批数据重新拟合 PCA 的逻辑。

### 3.2 Pipeline / Experiment 层

现有 `pipeline/` 暂时保留为实验兼容层，继续支持：

- `batch`
- `replay`
- `benchmark`
- `viz-demo`
- 完整导出产物
- 可视化数据
- 研究型标签统计和风险分析

后续可以逐步把画像、拓扑、audit 迁到 `experiment/`，但第一阶段不强行大规模搬迁。

## 4. 新入口设计

新增入口：

```bash
python3 -m trident_demo online --config trident_demo/configs/online.yaml
```

作用：

- 强制输入源为 Redis Stream。
- 强制 `runtime.perf_mode=true`。
- 强制 `runtime.performance_benchmark=true`。
- 关闭可视化、拓扑、metric audit、decision tree。
- 强制跳过 CSV 注入。
- 默认使用 `online.yaml` 作为基础配置。
- 默认认为 Redis 是独立服务，不由 Trident 自动启动。

可选参数：

- `--max-rows N`
- `--output-dir PATH`
- `--redis-url URL`
- `--redis-stream KEY`
- `--window-size N`
- `--start-redis`

## 5. 迁移策略

第一阶段：

```text
新增 runtime 子包
  -> 新增 online runner
  -> 新增 online CLI
  -> 保持旧 run 入口不变
  -> smoke 测试 import / CLI / 编译
```

第二阶段：

```text
把 pipeline/experiment.py 中的通用预处理逐步改为调用 runtime.preprocessing
  -> 先 Redis perf_mode
  -> 再普通 Redis
  -> 最后 CSV 实验链路
```

第三阶段：

```text
把画像、拓扑、audit、decision tree 搬到 experiment/
  -> pipeline 只负责调度
  -> runtime 只负责线上处理
```

## 6. 验收标准

第一阶段验收：

- `python3 -m trident_demo --help` 正常。
- `python3 -m trident_demo online --help` 正常。
- `python3 -m compileall trident_demo/runtime trident_demo/cli.py` 正常。
- 旧入口 `python3 -m trident_demo run --help` 仍存在。
- 新文档说明 runtime 与实验层边界。

完整后续验收：

- Redis online 模式能在有 Redis 数据时产出最小 benchmark。
- 旧 benchmark 输出不变。
- `runtime/` 不引用 `export/decision_tree_analysis.py`、`export/visualization.py` 等实验导出模块。
