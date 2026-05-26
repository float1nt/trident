# Runtime Refactor Result

本文档记录本次 runtime / experiment 分层改造的实际结果、冒烟测试和后续清理项。

## 1. 已完成的修改

### 1.1 新增 runtime 子包

新增目录：

```text
trident_demo/runtime/
  __init__.py
  schema.py
  preprocessing.py
  online_runner.py
```

职责：

- `schema.py`：线上预处理使用的字段和特征常量。
- `preprocessing.py`：线上安全的 DataFrame 预处理和特征矩阵构建。
- `online_runner.py`：Redis online 入口的配置裁剪和运行封装。

### 1.2 新增 online CLI

新增命令：

```bash
python3 -m trident_demo online --config trident_demo/configs/online.yaml
```

该入口会强制启用线上 Redis 流式处理模式：

- `input.source=redis_stream`
- `runtime.perf_mode=true`
- `runtime.performance_benchmark=true`
- `inject.enabled=false`
- `decision_tree.enabled=false`
- `visualization.enabled=false`
- `visualization.live_flush_enabled=true`
- `visualization.live_flush_metric_audit=false`
- `input.redis.apply_runtime_filters=false`

可选覆盖参数：

```bash
--max-rows N
--output-dir PATH
--redis-url URL
--redis-stream KEY
--window-size N
--start-redis
```

默认情况下 `online` 不启动 Redis，符合 Suricata、Redis、Trident 三服务独立部署的目标。只有显式传入 `--start-redis` 时，才会使用 demo 的 docker compose preflight 启动 Redis。

### 1.3 Redis perf path 接入 runtime 预处理

`TridentStreamingExperiment._prepare_loaded_dataframe()` 中，当输入是 Redis 且未显式开启 `apply_runtime_filters` 时，会调用：

```python
trident_demo.runtime.preprocessing.preprocess_runtime_dataframe()
```

这条路径明确排除了实验逻辑：

- 不做 `year_include`
- 不做 `attack_type_include / exclude`
- 不做 `attack_sample_per_type`
- 不做 `benign_sample_max_rows`

保留线上必需逻辑：

- `Label` / `Timestamp` 缺省补齐
- 时间解析和排序
- `LabelNorm`
- 缺失值处理
- 全零规则过滤
- `max_rows` 截断

### 1.4 特征构建统一到 runtime

旧的 `preprocess_features()` 现在转调用：

```python
trident_demo.runtime.preprocessing.build_feature_frame()
```

这样旧实验入口和新 online 入口共享同一套特征选择逻辑：

- 删除环境字段
- 选择数值列
- 支持 `all_numeric_no_env`
- 支持 `stable_stats_no_env`
- 支持 `compact_stats_no_env`
- 处理 `NaN/inf`

### 1.5 online 接入完整窗口处理

`pipeline/experiment.py` 中已抽出：

```python
TridentStreamingExperiment._process_stream_windows()
```

旧 `run()` 的窗口循环和新的 Redis online 路径现在共用这段逻辑。online 每个窗口都会执行：

- tSieve 推理。
- UNKNOWN 样本写入 `TMagnifier` 缓冲。
- `TMagnifier.pop_new_class_clusters()` 触发 DBSCAN。
- `_create_new_learners_from_clusters()` 创建 `NEW_*` 学习器。
- 已接收样本进入增量重训练判断和 `fit_incremental()`。
- 输出 `learner_count_over_time.csv`、`sample_assignments.csv`、`performance_summary.json`、`trident_performance_benchmark.*`。

因此 `online` 已经接入完整 Trident 窗口闭环；它和实验入口的区别主要是输出被裁剪，不导出完整 dataset profile、topology、metric audit、decision tree。

## 2. 保持兼容的部分

旧入口仍然保留：

```bash
python3 -m trident_demo run --profile batch
python3 -m trident_demo run --profile replay
python3 -m trident_demo run --profile benchmark
python3 -m trident_demo run --profile viz-demo
```

这些入口继续走现有实验 pipeline，因此原有数据画像、拓扑、metric audit、decision tree、benchmark 报告仍然可用。

## 3. 冒烟测试结果

已执行：

```bash
python3 -m compileall trident_demo/runtime trident_demo/pipeline/experiment.py trident_demo/cli.py
python3 -m trident_demo --help
python3 -m trident_demo online --help
python3 -m trident_demo run --help
python3 -c "from pathlib import Path; from trident_demo.runtime.online_runner import prepare_online_config; ..."
```

结果：

- 编译通过。
- 顶层 CLI 能看到 `run` 和 `online` 两个命令。
- `online --help` 正常展示参数。
- `run --help` 仍然正常展示旧 profile 参数。
- `prepare_online_config()` 能正确设置：
  - `runtime.perf_mode=True`
  - `input.source=redis_stream`
  - Redis stream 覆盖参数
  - `stream.window_size` 覆盖参数
  - 输出目录 run_id

说明：

- 本次没有实际消费 Redis 数据，因为当前冒烟测试只验证代码可导入、参数可解析、配置可生成。
- 真正端到端在线测试需要 Redis Stream 中存在 `cic_flow` 数据，或配合 stress 启动 Suricata / tcpreplay。

## 4. 已清理的冗余

已完成：

- 新增 `runtime.preprocessing`，把线上预处理规则从实验语义中独立出来。
- `preprocess_features()` 改为复用 runtime 特征构建函数。
- Redis perf path 走 runtime 预处理，不再走实验采样/过滤。
- Redis perf path 复用完整窗口处理逻辑，不再只有 `classify_batch()` 推理。
- `online` 入口集中设置 runtime 所需裁剪项，不需要手动在 benchmark 配置里到处关闭导出项。

暂未强行清理：

- `pipeline/experiment.py` 里仍保留部分历史常量和实验方法。
- 普通 Redis 非 `perf_mode` 路径仍在 `_load_dataset()` 内保留旧实验兼容逻辑。
- 完整画像、拓扑、audit 仍在 `pipeline/experiment.py` 中。

保留原因：

- 当前目标是先建立 runtime 边界并跑通冒烟。
- 一次性删除实验代码会影响旧 profile 的稳定性。
- 后续应按模块逐步迁出，而不是一次性大改。

## 5. 后续建议

下一阶段建议按这个顺序继续：

1. 新建 `trident_demo/runtime/engine.py`，把 `_process_stream_windows()` 从 `pipeline/experiment.py` 进一步迁出。
2. 新建 `trident_demo/experiment/`，迁移 dataset profile、topology、metric audit、decision tree。
3. 将普通 Redis benchmark 也拆成明确的 `experiment benchmark` 和 `runtime online` 两条入口。
4. 为 runtime 增加真正的端到端 smoke 配置，使用小 Redis Stream 样本跑一次 `online --max-rows N`。
5. 将 scaler / PCA / feature schema 固化为可版本化 artifact，避免线上运行时拟合。
