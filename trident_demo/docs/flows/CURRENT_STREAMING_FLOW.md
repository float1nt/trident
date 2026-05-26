# Current Streaming Flow

本文档说明当前代码中“流式处理”实际怎么走。范围包括新拆出的 `online` 入口、Redis `perf_mode` 路径，以及旧 `run --profile replay/benchmark` 的兼容路径。

## 1. 当前有两条 Redis 流式相关入口

### 1.1 线上流式入口

命令：

```bash
python3 -m trident_demo online --config trident_demo/configs/online.yaml
```

入口文件：

```text
trident_demo/cli.py
  -> trident_demo/runtime/online_runner.py
  -> trident_demo/pipeline/runner.py
  -> trident_demo/pipeline/experiment.py
```

这个入口会强制进入 Redis online runtime 模式：

```text
input.source = redis_stream
runtime.perf_mode = true
runtime.performance_benchmark = true
inject.enabled = false
decision_tree.enabled = false
visualization.enabled = false
input.redis.apply_runtime_filters = false
```

它的目标是尽量贴近真实线上处理：Trident 作为独立消费者连接已有 Redis 服务，从 Redis Stream 按窗口消费数据，只保留最小 benchmark 输出。

### 1.2 旧实验入口

命令：

```bash
python3 -m trident_demo run --profile replay
python3 -m trident_demo run --profile benchmark
```

这条入口仍然保留完整实验能力：

- Redis preflight
- 可选 CSV 注入 Redis
- 完整实验 pipeline
- 标签画像
- 拓扑
- metric audit
- benchmark 报告
- 可视化产物

旧入口适合做实验分析，不是纯线上 runtime。

## 2. online 模式的完整流程

当前推荐的线上流式路径如下：

```text
CLI online
  -> prepare_online_config()
  -> PipelineRunner(profile=benchmark, no_inject=true)
  -> preflight Redis
  -> TridentStreamingExperiment.run()
  -> _run_perf_mode_redis_stream()
  -> iter_redis_flow_windows()
  -> runtime preprocessing
  -> feature matrix
  -> init learners
  -> full window processing
       -> inference
       -> UNKNOWN buffering
       -> DBSCAN clustering
       -> NEW learner creation
       -> incremental retraining
  -> minimal artifacts
```

更详细的时间线：

```text
1. 读取基础 YAML 配置
2. online_runner 强制裁剪成线上配置
3. 创建 run_id 和 output_dir
4. 检查 Redis 是否可达
5. 跳过 CSV 注入
6. 创建 TridentStreamingExperiment
7. 检查 runtime.perf_mode=true 且 input.source=redis_stream
8. 进入 _run_perf_mode_redis_stream()
9. 从 Redis 读取第一个窗口
10. 对第一个窗口做 runtime 预处理
11. 构建特征矩阵
12. 用初始段创建初始学习器
13. 对第一个窗口剩余数据执行完整窗口处理
14. 持续从 Redis 读取后续窗口
15. 每个窗口预处理、特征对齐、推理、聚类、新学习器创建、增量重训练
16. 输出窗口统计、样本分配和性能产物
```

## 3. Redis 数据如何进入 Trident

Redis 读取函数在：

```text
trident_demo/io/redis_loader.py
```

online 模式使用：

```text
iter_redis_flow_windows(redis_cfg, window_size=...)
```

处理方式：

```text
Redis Stream
  -> XREADGROUP / XREAD
  -> normalize_flow_record()
  -> records -> DataFrame
  -> yield 一个窗口 DataFrame
```

每个 Redis message 会做字段归一化：

- `src_ip` / `srcip` / `source_ip` -> `Src IP`
- `dst_ip` / `dest_ip` -> `Dst IP`
- `src_port` -> `Src Port`
- `dst_port` -> `Dst Port`
- `proto` / `protocol` -> `Protocol`
- `timestamp` -> `Timestamp`
- `label` -> `Label`

如果消息没有 `Label`，默认填：

```text
0000|UNLABELED
```

## 4. 当前线上预处理做什么

online 模式下，Redis 数据会走：

```text
trident_demo/runtime/preprocessing.py
  -> preprocess_runtime_dataframe()
```

这条路径只保留线上必需逻辑。

### 4.1 输入补齐

如果缺少 `Label`：

```text
Label = 0000|UNLABELED
```

如果缺少 `Timestamp`：

```text
生成递增 Timestamp
```

### 4.2 时间处理

```text
Timestamp 解析
  -> 丢弃无效时间
  -> 按 Timestamp 排序
```

作用是保证窗口内数据顺序稳定。

### 4.3 标签规范化

生成：

```text
LabelNorm = normalize_label(Label)
```

即使线上数据通常无标签，`LabelNorm` 仍用于兼容初始化、统计和调试。

### 4.4 缺失值处理

当前规则：

- `Protocol` 生成 `is_non_tcp`
- `FWD Init Win Bytes` 的 `-1/NaN` 转 `0`，生成 `fwd_init_win_missing_flag`
- `Bwd Init Win Bytes` 的 `-1/NaN` 转 `0`，生成 `bwd_init_win_missing_flag`
- `Flow Bytes/s` 的 `inf/-inf/NaN` 转 `0`，生成 `flow_bytes_s_missing_flag`
- `benign_type` 缺失填 `UNKNOWN`

### 4.5 全零过滤

如果配置了 `drop_when_all_numeric_zero_rules`，会丢弃指定列全为零的行。

典型例子：

```text
Total Fwd Packet == 0
and
Total Bwd packets == 0
```

### 4.6 明确不做的实验逻辑

online runtime 预处理不会做：

- `year_include`
- `year_benign_exclude`
- `attack_type_include`
- `attack_type_exclude`
- `attack_sample_per_type`
- `benign_sample_max_rows`
- dataset label distribution
- topology
- metric audit
- decision tree

这些属于实验路径。

## 5. 特征矩阵如何构建

特征构建函数：

```text
trident_demo/runtime/preprocessing.py
  -> build_feature_frame()
  -> build_feature_matrix()
```

步骤：

```text
DataFrame
  -> 删除环境字段
  -> 只保留数值列
  -> 按 feature_profile 选择特征
  -> NaN/inf 转 0
  -> float32 NumPy matrix
```

删除的环境字段：

```text
id
Flow ID
Src IP
Dst IP
Src Port
Dst Port
Protocol
Timestamp
Label
Attempted Category
```

支持的 feature profile：

- `all_numeric_no_env`
- `stable_stats_no_env`
- `compact_stats_no_env`

online 模式第一批窗口会确定 `feature_cols`，后续窗口会按这个列集合重新对齐：

```text
feat_df_batch.reindex(columns=feature_cols, fill_value=0.0)
```

这样可以避免后续 Redis message 字段缺失或新增字段导致维度变化。

## 6. 初始学习器如何创建

online 模式先读取第一个 Redis 窗口，然后构建初始学习器。

代码路径：

```text
_run_perf_mode_redis_stream()
  -> _build_initial_learners()
```

初始化目标行数：

```text
init_target = max(
  window_size * 2,
  stream.init_benign_count,
  5000
)
```

初始化逻辑：

```text
第一批 Redis 数据
  -> runtime 预处理
  -> 特征矩阵
  -> 根据 init_ratio / init_benign_count 选初始化段
  -> 如果 init_known_mode=benign_only，则筛良性
  -> 按 LabelNorm 分组
  -> TSieve.add_learner()
```

注意：

- 如果 Redis 数据没有真实标签，默认是 `0000|UNLABELED`。
- 如果配置允许 `allow_unlabeled_initial_learner=true`，没有良性标签时会用 unlabeled 数据作为初始化候选。
- 这是为了让线上无标签输入仍然可以启动初始模型。

## 7. 每个窗口如何处理

online 模式当前窗口处理是轻量 perf path：

```text
process_batch()
  -> classify_batch()
  -> 记录 sample_assignments
  -> 更新 learner_count_over_time
  -> 累计 perf_stats
```

当前 online perf path 主要做推理测速：

- 会执行 `TSieve.classify_batch()`
- 会记录 `stream_inference`
- 会记录 `window_total_seconds_total`
- 会输出 learner 数量变化

当前 online perf path 不执行完整实验路径中的重导出。

当前 `_run_perf_mode_redis_stream()` 已经不再只做轻量推理。Redis online 路径会调用从旧 `run()` 抽出的 `_process_stream_windows()`，因此每个窗口都会走 UNKNOWN 缓冲、DBSCAN 聚类、新学习器创建和增量重训练。它仍然是“最小输出路径”：不会导出完整拓扑、metric audit、decision tree 等实验产物。

## 8. 输出产物

online 模式输出目录：

```text
trident_demo/outputs/<run_id>/
```

主要产物：

```text
learner_count_over_time.csv
performance_summary.json
trident_performance_benchmark.json
trident_performance_benchmark.md
run.log
```

这些产物关注性能，不关注完整实验画像。

## 9. 时间消耗口径

online 模式主要看：

- `io_source_read`：Redis 读取等待和解析时间
- `io_preprocess`：runtime 预处理时间
- `io_feature_matrix`：特征矩阵构建时间
- `init_learners`：初始学习器训练时间
- `stream_inference`：模型推理时间
- `stream_window_total` / `window_total_seconds_total`：窗口处理总时间
- `export_run_artifacts`：最小产物导出时间

核心速度指标：

```text
flows_per_second_inference
stream_flow_count / detect_seconds_total
```

以及：

```text
stream_flow_count / window_total_seconds_total
```

如果配合 `stress` 跑，还要结合：

- `tcpreplay` 发送时间
- Suricata flow 收尾时间
- Redis XLEN 增长曲线
- Trident wait ratio

## 10. 旧 replay / benchmark 和 online 的区别

| 模式 | 数据读取 | 预处理 | 输出 | 适用场景 |
|---|---|---|---|---|
| `online` | Redis 按窗口读取 | runtime 预处理 | 最小性能产物 | 线上流式吞吐 |
| `run --profile benchmark` | 通常先拉一批 Redis 数据 | 实验兼容预处理 | 完整 benchmark + 可视化 | 实验评估 |
| `run --profile replay` | 通常先拉一批 Redis 数据 | 实验兼容预处理 | 完整 demo 产物 | 回放验证 |

简化理解：

```text
online:
  Redis -> window -> runtime preprocess -> inference -> minimal benchmark

benchmark/replay:
  Redis batch -> experiment pipeline -> full analysis -> full artifacts
```

## 11. 当前限制

当前 online 模式已经完成入口和 runtime 预处理隔离，但仍有几个限制：

- online 入口复用了 `TridentStreamingExperiment`，还没有完全独立成 `TridentOnlineEngine`。
- runtime 预处理已拆出，但普通 Redis 非 perf path 仍保留旧实验兼容逻辑。
- online perf path 当前重点是推理吞吐，不导出完整实验画像。
- scaler / PCA / feature schema 还没有固化成版本化 artifact。

后续如果要进一步接近真实部署，应继续拆：

```text
TridentOnlineEngine
  -> RuntimePreprocessor
  -> RedisWindowConsumer
  -> OnlineStateStore
  -> MinimalResultSink
```
