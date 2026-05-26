# Trident Demo 数据处理流程说明

本文档梳理 `trident_demo/` 当前代码中的数据处理链路，范围包括普通实验、Redis replay/benchmark、viz-demo 数据准备、E2E 压测以及前端展示读取流程。

## 1. 总体入口

主入口是 `python3 -m trident_demo run --profile <profile>`：

- `trident_demo/__main__.py` 调用 `trident_demo/cli.py`。
- `cli.py` 解析 `run` 子命令和 `--profile`、`--config`、`--max-rows` 等参数。
- `pipeline/runner.py` 根据 profile 选择默认配置：
  - `batch` -> `configs/batch.yaml`
  - `replay` -> `configs/replay.yaml`
  - `benchmark` -> `configs/benchmark.yaml`
  - `viz-demo` -> `configs/viz_demo.yaml`
- `prepare_config()` 读取 YAML、生成 `run_id`、建立输出目录 `trident_demo/outputs/<run_id>/`，并把最终输出目录写回 `cfg["paths"]["output_dir"]`。
- `PipelineRunner.run()` 按 profile 执行编排阶段、实验阶段和收尾阶段。

总体链路：

```text
CLI 参数
  -> 读取 YAML 配置
  -> 生成 run_id / output_dir / logger / PerformanceRecorder
  -> 可选数据准备或 Redis 预检查/注入
  -> TridentStreamingExperiment.run()
  -> 导出 CSV/JSON/PNG/benchmark
  -> postrun 打印输出位置
```

## 2. Profile 级数据流

### 2.1 batch

`batch` 是离线 CSV 分析路径。

```text
configs/batch.yaml
  -> paths.data_dir + paths.input_files
  -> 逐个 pd.read_csv()
  -> 标签补 year 前缀 / 时间排序 / 过滤 / 特征矩阵
  -> Trident 流式窗口处理
  -> outputs/<run_id>/...
```

关键点：

- 默认从 `/home/data` 读取多个 2017、2019、2026 CSV。
- CSV 必须包含 `Label`；缺失会报错。
- 如果标签没有 `YYYY|` 前缀，会根据文件路径推断 2017/2019 并补前缀；无法推断则保留原标签并记录 warning。
- Redis 相关配置在 `batch.yaml` 中存在，但 `input.source: csv`，不会走 Redis 读取。

### 2.2 replay / benchmark

`replay` 和 `benchmark` 默认是 Redis Stream 输入路径，二者配置基本一致，`benchmark` 强制开启性能报告。

```text
configs/replay.yaml 或 configs/benchmark.yaml
  -> preflight 检查 Redis
  -> 可选 CSV 注入 Redis Stream
  -> 从 Redis Stream 读取 cic_flow 消息
  -> 标准化字段 / 时间排序 / 特征矩阵
  -> Trident 流式窗口处理
  -> benchmark + 可视化产物
```

关键点：

- `preflight_stage()` 会先 ping Redis；如果不可达且未设置 `--skip-docker`，会尝试用 `suricata-cic-redis-live/docker-compose.yml` 启动 Redis。
- `inject.enabled` 默认是 `false`，所以 replay/benchmark 默认读取已有 `suricata:cic_flow` stream。
- 如果启用注入，`orchestration/redis_inject.py` 会读取 CSV，并将每行封装为 `event_type=cic_flow` 的 JSON message，通过 `XADD` 写入 Redis Stream。
- Redis 输入由 `io/redis_loader.py` 读取，支持 list/queue 和 stream/streams；当前配置使用 stream。

### 2.3 viz-demo

`viz-demo` 会先构建对齐数据集，再走离线 CSV 分析。

```text
2017/2019/2026 原始 CSV
  -> orchestration/data_prep.py
  -> 对齐共同字段 / 标签标准化 / 抽样
  -> data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv
  -> TridentStreamingExperiment.run()
  -> 可视化产物
```

数据准备逻辑：

- `orchestration/viz_data_prep.py` 调用 `data_prep.main()`。
- 2019 字段名会通过 `RENAME_2019_TO_2017` 映射到 2017 风格。
- 三类数据只保留共同特征列，且必须包含 `Timestamp`。
- 2017/2019 的 `BENIGN` 会标为 `YYYY|BENIGN`。
- 2026 全部视为良性类型，标为 `2026|BENIGN|<SUBTYPE>`。
- 攻击标签标为 `YYYY|<ATTACK_NAME>`。
- 默认抽样规则：每年良性最多 100000，攻击每类最多 10000，良性再按 `benign_multiplier=5` 扩增。
- 输出 CSV 和 report JSON 到 `data/`。

## 3. 输入标准化与特征构建

核心逻辑在 `pipeline/experiment.py::TridentStreamingExperiment._load_dataset()`。

### 3.1 CSV 输入

CSV 输入流程：

```text
ordered_data_files()
  -> pd.read_csv()
  -> 检查 Label
  -> 推断/补齐 year tag
  -> concat
  -> 全量 DataFrame 进入后续 Trident 预处理
```

`ordered_data_files()` 使用配置中的 `paths.input_files` 顺序；未配置时默认读取 `monday.csv` 到 `friday.csv`。

CSV 输入是“先全量读入，再按窗口处理”的模式。也就是说，CSV 文件不会按窗口边读边处理，而是先将所有配置文件读取并合并为一个完整 `DataFrame`，再统一执行时间排序、标签归一化、过滤、缺失值处理和特征矩阵构建。

完整流程可以理解为：

```text
CSV 文件
  -> 全量 pd.read_csv() / concat
  -> Timestamp 排序
  -> LabelNorm 归一化
  -> runtime 过滤 / 采样 / 缺失值处理
  -> 构建完整 x_all 特征矩阵
  -> 前 init 段构建初始学习器
  -> 剩余数据按 stream.window_size 分批进入 Trident 流式处理
```

因此，CSV 的“窗口”只发生在 Trident 内部处理阶段，不发生在文件读取阶段。

### 3.2 Redis 输入

Redis 输入流程：

```text
load_redis_flows()
  -> XREAD / XREADGROUP 或 BLPOP / LPOP
  -> normalize_flow_record()
  -> event_type 过滤
  -> records -> DataFrame
```

字段标准化规则：

- 常见别名统一为 CIC 风格字段，例如 `src_ip` -> `Src IP`、`dst_port` -> `Dst Port`。
- `Protocol` 字符串会映射为数字：`tcp=6`、`udp=17`、`icmp=1`。
- 缺失 `Label` 时，默认填 `0000|UNLABELED`，除非 `require_label=true`。
- 支持从 `message/event/json/eve/record/data/payload/cic_flow` 等 wrapper 中解包。

Redis 输入需要区分两种运行方式。

第一种是普通 `replay/benchmark` 模式。当前 `_load_dataset()` 会调用 `load_redis_flows()`，从 Redis Stream 读取一批消息，直到达到 `max_messages` 或 `idle_timeout_seconds`，然后组装成一个完整 `DataFrame`。之后的处理方式和 CSV 类似：统一预处理、构建完整特征矩阵，再由 Trident 按 `stream.window_size` 切窗口处理。

普通 Redis 模式流程：

```text
Redis Stream
  -> load_redis_flows() 拉取一批消息
  -> records -> DataFrame
  -> Timestamp 排序
  -> LabelNorm 归一化
  -> 缺失值处理 / max_rows 截断
  -> 构建完整 x_all 特征矩阵
  -> 前 init 段构建初始学习器
  -> 剩余数据按 stream.window_size 分批进入 Trident
```

所以普通 Redis 模式不是严格意义上的“到一个窗口才进入 Trident”，而是“先从 Redis 拉取一批，再窗口化处理”。

第二种是 `runtime.perf_mode=true` 且输入为 Redis 的模式。此时不会先 drain 出完整数据集，而是走 `_run_perf_mode_redis_stream()` 和 `iter_redis_flow_windows()`，每次从 Redis 读取约 `window_size` 条消息，当前窗口预处理后立即进入 Trident。

perf_mode Redis 流程：

```text
Redis Stream
  -> iter_redis_flow_windows(window_size)
  -> 每次读取一个窗口 DataFrame
  -> 当前窗口预处理
  -> 当前窗口进入 Trident
  -> 再读取下一窗口
```

因此可以总结为：

```text
CSV：全量读入 -> 再按窗口处理
普通 Redis：先从 Redis 拉一批 -> 再按窗口处理
perf_mode Redis：按窗口从 Redis 拉取 -> 到窗口就处理
```

### 3.3 通用预处理

CSV 和 Redis 最终都会进入相同预处理路径：

```text
DataFrame
  -> 补 Label / Timestamp 缺省值
  -> Timestamp 解析，丢弃无效时间
  -> 按 Timestamp 排序
  -> LabelNorm = normalize_label(Label)
  -> 可选 runtime filters / attack sampling
  -> 缺失值策略
  -> 全零规则过滤
  -> max_rows 截断
  -> preprocess_features()
  -> x_all float32 特征矩阵
```

通用预处理的目标是把 CSV 或 Redis 进入的数据统一成 Trident 可以稳定处理的格式。每一步的作用如下。

#### 3.3.1 补 Label / Timestamp 缺省值

作用：保证后续流程一定有标签列和时间列。

- 如果没有 `Label`，填默认标签，例如 `0000|UNLABELED`。
- 如果没有 `Timestamp`，生成一个递增时间序列。

原因：

- `Label` 用于初始化学习器、统计、评估和画像分析。
- `Timestamp` 用于时间排序、流式窗口顺序、时间画像和拓扑/审计分析。

#### 3.3.2 Timestamp 解析并丢弃无效时间

作用：把字符串或混合格式时间统一转成 pandas datetime。

如果时间解析失败，该行会得到无效时间 `NaT`，随后被丢弃。

原因：

- Trident 后续需要按时间顺序模拟流式处理。
- 无效时间会破坏排序、窗口顺序和时间相关统计。

#### 3.3.3 按 Timestamp 排序

作用：让样本按真实时间顺序进入 Trident。

原因：

- Trident 是流式处理逻辑，输入顺序会影响初始学习器和后续窗口。
- 初始学习器使用数据前段创建。
- 后续 unknown 聚类、增量更新、窗口统计都依赖时间顺序。

#### 3.3.4 生成 LabelNorm

作用：通过 `normalize_label(Label)` 把标签统一为规范格式。

示例：

```text
BENIGN           -> BENIGN
2017|BENIGN      -> 2017|BENIGN
2019|DrDoS_DNS   -> 2019|DRDOS_DNS
2026|BENIGN|DNS  -> 2026|BENIGN|DNS
```

原因：

- 统一大小写和基础攻击名。
- 保留年份前缀。
- 保留 2026 良性子类型。
- 后续可以稳定识别良性标签、按标签建初始学习器、统计攻击比例和生成画像。

#### 3.3.5 runtime filters / attack sampling

作用：按配置过滤或采样数据。

支持的过滤配置：

- `year_include`：只保留指定年份。
- `year_benign_exclude`：排除指定年份的良性样本。
- `attack_type_include`：只保留指定攻击类型；默认仍保留良性。
- `attack_type_exclude`：排除指定攻击类型；默认仍保留良性。
- `protocol_include`：只保留指定协议，例如 `tcp`、`udp`、`other`、`non_udp`。

支持的采样配置：

- `attack_sample_per_type`：每类攻击最多保留多少样本。
- `benign_sample_max_rows`：良性最多保留多少样本。

原因：

- 控制实验范围。
- 做子集实验。
- 降低数据量。
- 调整良性/攻击比例。
- 排除不希望参与建模的攻击族或协议类型。

注意：Redis 默认跳过这些数据集特定过滤和采样，除非 `input.redis.apply_runtime_filters=true`。

#### 3.3.6 缺失值策略

作用：把模型不能直接处理的特殊缺失、无穷值、不适用值变成可训练数值，并尽量保留缺失信息。

当前规则：

- `Protocol` 生成 `is_non_tcp`。
- `FWD Init Win Bytes` 中的 `-1` 和 `NaN` 变成 `0`，并生成 `fwd_init_win_missing_flag`。
- `Bwd Init Win Bytes` 中的 `-1` 和 `NaN` 变成 `0`，并生成 `bwd_init_win_missing_flag`。
- `Flow Bytes/s` 中的 `inf/-inf/NaN` 变成 `0`，并生成 `flow_bytes_s_missing_flag`。
- `benign_type` 缺失填 `UNKNOWN`。

原因：

- AutoEncoder / IsolationForest 不能直接处理 `NaN`、`inf` 和字符串缺失。
- CIC 特征中的 `-1` 经常表示“不适用”，直接作为数值会误导模型。
- missing flag 可以告诉模型“该字段原本缺失或不适用”，避免完全丢失信息。

缺失值处理报告写入：

```text
missing_value_strategy_report.json
```

#### 3.3.7 全零规则过滤

作用：按配置丢弃某些关键数值列全为 0 的异常行。

例如 `batch.yaml` 中的规则：

```yaml
drop_when_all_numeric_zero_rules:
  - name: zero_fwd_bwd_packet_counts
    enabled: true
    columns:
      - Total Fwd Packet
      - Total Bwd packets
    eps: 0.0
    treat_nan_as_zero: true
```

含义：如果 `Total Fwd Packet` 和 `Total Bwd packets` 都为 0，就丢弃该行。

原因：

- 这种 flow 通常没有有效通信行为。
- 会污染特征分布。
- 可能让模型学到无意义的零向量模式。

#### 3.3.8 max_rows 截断

作用：限制最多使用多少行。

原因：

- 快速调试。
- 小规模 benchmark。
- 防止一次处理过多数据。
- Redis 输入时也会同步控制 `max_messages`。

#### 3.3.9 preprocess_features()

作用：从完整 DataFrame 中提取模型输入特征。

它会先删除环境/泄漏字段：

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

然后只保留数值列，并根据 `runtime.feature_profile` 选择特征集合：

- `all_numeric_no_env`：全部数值特征。
- `stable_stats_no_env`：`STABLE_STATS_FEATURES` 中存在的稳定统计特征。
- `compact_stats_no_env`：`COMPACT_STATS_FEATURES` 中存在的较小特征子集，当前多数配置使用该模式。

最后会把 `inf/-inf/NaN` 再次填成 `0.0`。

原因：

- 避免模型直接学习 IP、端口、时间、标签等环境或泄漏字段。
- 保证输入全部是数值。
- 控制特征维度和稳定性。

#### 3.3.10 x_all float32 特征矩阵

作用：把 pandas 特征表转成 NumPy 矩阵，供模型训练和推理使用。

```text
feat_df.values.astype(np.float32)
```

原因：

- `TSieve` 的 AutoEncoder / IsolationForest 都基于数值矩阵。
- `float32` 更适合 PyTorch/GPU。
- 后续窗口处理都是基于 `x_all[left:right]` 切片完成的。

可以把通用预处理理解为三段：

```text
前半段：保证数据有 Label、Timestamp，并按时间排序
中间段：统一标签、过滤数据、处理缺失和异常值
后半段：去掉环境字段，提取数值特征，转成模型输入矩阵
```

### 3.4 特征选择

`preprocess_features()` 会删除环境/泄漏字段：

```text
id, Flow ID, Src IP, Dst IP, Src Port, Dst Port,
Protocol, Timestamp, Label, Attempted Category
```

然后只保留数值列，并按 `runtime.feature_profile` 选择特征：

- `all_numeric_no_env`：全部数值特征。
- `stable_stats_no_env`：`STABLE_STATS_FEATURES` 中存在的数值特征。
- `compact_stats_no_env`：`COMPACT_STATS_FEATURES` 中存在的数值特征，当前多数配置使用该模式。

所有 `inf/-inf/NaN` 最终填为 `0.0`。如果 `runtime.pca_n_components > 0`，还会做 PCA 并把特征列名改成 `pca_000...`。

## 4. Trident 核心处理流程

核心类是 `TridentStreamingExperiment`，由 `pipeline/stages/run_experiment.py` 创建并调用 `run()`。

### 4.0 按时间线的总流程

不管输入来自 CSV 还是普通 Redis，进入 `TridentStreamingExperiment.run()` 之后，时间线基本是下面这条主线：

```text
1. 读取数据源并做通用预处理
2. 构建特征矩阵 x_all
3. 导出数据集画像 / 网络拓扑
4. 构建初始学习器
5. 按窗口做在线分类
6. 把未知流量送入聚类器
7. 从未知聚类里创建新学习器
8. 对已接受样本做增量训练
9. 持续刷新窗口统计和 live 产物
10. 结束后导出学习器画像、风险、指标、图表、benchmark
```

其中真正耗时的步骤主要有这些：

- 数据源读取：`io_source_read`
- 通用预处理：`io_preprocess`
- 特征矩阵构建：`io_feature_matrix`
- 初始学习器训练：`init_learners`
- 窗口分类：`stream_inference`
- 未知样本聚类：`stream_cluster`
- 新学习器训练：`stream_create_learner`
- 增量重训练：`stream_retrain`
- 画像和拓扑导出：`export_dataset_profile`、`export_run_artifacts`、`export_visualization`

如果用 `PerformanceRecorder` 看指标，普通 run 里最常见的口径是：

```text
pipeline_total
  -> pipeline_preflight
  -> pipeline_redis_inject (replay/benchmark 可能有)
  -> pipeline_experiment
       -> io_load_total
       -> init_learners
       -> stream_window_total
       -> export_run_artifacts
       -> export_visualization
  -> pipeline_postrun
```

### 4.1 初始学习器构建

```text
data + x_all
  -> 根据 stream.init_ratio 取初始化段，至少 5000 行
  -> 如果 init_known_mode=benign_only，只保留良性标签
  -> 可按 init_benign_year 和 init_benign_count 进一步筛选
  -> 按 LabelNorm 分组
  -> TSieve.add_learner()
```

`TSieve.add_learner()`：

- 样本数低于 `min_class_samples` 不建模。
- 样本数超过 `max_train_per_class` 会随机下采样。
- `classifier_backend=ae` 时训练 AutoEncoder。
- `classifier_backend=iforest` 时训练 IsolationForest。
- 使用 `TScissors.fit_threshold()` 基于训练 loss 估计阈值。

这一段的耗时主要来自：

- `StandardScaler.fit_transform()`
- AutoEncoder 训练的多个 epoch
- IsolationForest 拟合
- 最终在训练集上重新算 loss 再估计 threshold

如果初始化段很大，`init_learners` 往往是前几个最显著的耗时点之一。

AutoEncoder 结构：

```text
input -> 256 -> 128 -> 64 -> 32 -> 64 -> 128 -> 256 -> input
```

解码阶段有 skip addition。

### 4.2 窗口式流处理

初始化段之后，按 `stream.window_size` 处理后续数据：

```text
for window in stream:
  classify_batch()
  -> 已识别样本分发到 accepted_by_learner
  -> 未识别样本进入 TMagnifier unknown_buffer
  -> DBSCAN 聚类 unknown_buffer
  -> 创建 NEW_* 学习器
  -> 可选小学习器重聚类
  -> 对已有学习器做增量更新
  -> 记录窗口指标和 live flush
```

分类逻辑：

- 每个学习器计算 reconstruction loss 或 IsolationForest loss。
- loss 小于阈值则视为该学习器接受该样本。
- 多个学习器接受时，默认优先非良性学习器，再选 loss 最低者；若 `uniform_learner_treatment=true` 则直接全局最低。
- 没有学习器接受则标为 `UNKNOWN`。

按每个窗口看，处理顺序是固定的，时间上大致可以理解成：

```text
window_start
  -> classify_batch()                # stream_inference
  -> UNKNOWN 收集 / accepted 分发
  -> pop_new_class_clusters()        # stream_cluster
  -> create_new_learners_from_clusters()
  -> maybe_recluster_small_learners()
  -> accumulate learner distributions
  -> 对每个 learner 判断是否触发 incremental update
  -> sample history + fit_incremental() + refresh_threshold()
  -> 写入 time_series / accept_trace / live flush
window_end
```

窗口内最耗时的部分通常是：

- `stream_inference`：对每个样本和每个学习器算 loss
- `stream_cluster`：unknown buffer 达到阈值后做标准化和 DBSCAN
- `stream_create_learner`：新类学习器训练
- `stream_retrain`：历史样本拼接后的增量重训练

其中 `stream_inference` 的成本与“学习器数量 × 窗口大小”近似成正比；学习器越多、窗口越大，这一步越重。

未知样本聚类：

- `TMagnifier.add_unknown()` 维护 unknown buffer，超过 `max_unknown_buffer` 会丢弃最老 unknown 并记录标签计数。
- `pop_new_class_clusters()` 在 buffer 达到 `cluster_trigger_size` 后使用 `StandardScaler + DBSCAN` 聚类。
- 聚类大小达到 `new_class_min_size` 才会生成候选新类。
- `_create_new_learners_from_clusters()` 将候选聚类训练为 `NEW_1`、`NEW_2` 等新学习器。
- 可选 `cluster_purity_gate` 会基于良性概率、结构可分性、路由一致性等规则拒绝混杂聚类；被拒绝样本可重新放回 unknown 或丢弃。

增量更新：

- 每个窗口中被某个学习器接受的样本会进入该学习器的历史池。
- 达到 `increment_min_samples` 或满足 `increment_use_last_train_gap` 后触发更新。
- 可选 gate 包括：
  - 良性置信过滤。
  - 冻结良性学习器增量更新。
  - 新学习器冷却窗口。
  - 每学习器最大重训次数。
  - 特征漂移 gate。
  - 路由一致性 gate。
  - IsolationForest guard。
- 更新样本由新样本和历史样本拼接而成。
- 更新后重新刷新阈值。

增量更新这一段通常也是耗时大头，因为它包含了：

- 过滤和采样决策
- 历史样本抽样
- `fit_incremental()` 的再次训练
- `refresh_threshold()` 的 loss 重新估计
- 更新 trace、画像和分布统计

当学习器很多、历史池很大、`increment_epochs` 较高时，`stream_retrain` 会显著拉长窗口耗时。

### 4.3 perf_mode Redis 流式模式

当 `runtime.perf_mode=true` 且输入是 Redis 时，使用 `_run_perf_mode_redis_stream()`：

- 通过 `iter_redis_flow_windows()` 连续按窗口从 Redis 读取，不先 drain 全部数据。
- 每个窗口读完后立即预处理、立即进入 Trident，不会先把所有 Redis 消息拼成一个完整离线数据集。
- 第一批窗口先用于构建初始学习器，后续窗口边读边处理。
- 只输出最小产物：`learner_count_over_time.csv`、`performance_summary.json`、benchmark 报告。
- 跳过大量画像、拓扑、图像导出，用于性能压测。

和普通 Redis 模式相比，`perf_mode` 的关键不同是：

- 普通 Redis 会先 `load_redis_flows()` 拉出一批完整数据，再走离线式的 `x_all` 构建和窗口处理。
- `perf_mode` 不构建完整离线批次，而是直接按窗口消费 stream。
- 普通 Redis 会导出完整画像和可视化产物。
- `perf_mode` 会尽量关闭这些非核心耗时项，把时间尽量集中在 `io_source_read`、`io_preprocess`、`stream_inference`、`stream_retrain` 上。

所以如果你想看“在线流式处理真正的速度”，应该优先看 `perf_mode` 的 Redis 结果；如果你想看“完整 demo 一轮跑完的总成本”，看普通 benchmark 更合适。

## 5. 导出产物

每次普通 run 写到 `trident_demo/outputs/<run_id>/`。主要产物分为几类。

### 5.1 数据集画像

- `dataset_label_distribution.csv`：按标签统计数量、比例、年份、基础标签、协议/特征画像。
- `dataset_label_distribution_summary.json`：总体行数、标签数、良性/攻击比例、Top 标签。
- `dataset_label_feature_attack_correlation.json/png`：标签级特征与攻击属性相关性。
- `dataset_network_topology.json`：按标签、良性/攻击/combined 生成 host/endpoint 网络拓扑。
- `missing_value_strategy_report.json`：缺失值处理报告。

### 5.2 学习器画像

- `learner_count_over_time.csv/png`：每个窗口结束时学习器数量和 unknown buffer 大小。
- `learner_creation_distribution.csv`：学习器创建时的标签分布。
- `learner_train_batch_label_distribution.csv`：初始、新建、增量训练批次的标签分布。
- `learner_increment_loss_trace.csv`：增量更新前后 loss 变化。
- `learner_fit_loss_trace.csv`：训练 epoch loss 轨迹。
- `learner_label_distribution.csv`：每个学习器最终吸收样本的标签分布、攻击占比、协议/时序/端口/特征画像。
- `learner_creation_flow_previews.json`：每个学习器创建时的样本预览。
- `learner_creation_row_indices.json`：创建学习器所用原始行号。
- `learner_risk_scores.csv`：无监督风险评分。
- `sample_learner_assignments.csv`：每个样本的最终学习器归属。
- `learner_accept_trace.csv`：样本被接受后是否用于增量训练以及过滤原因。

### 5.3 指标、聚合与可视化

- `metrics.json`：风险 FPR/FNR、协议簇摘要、metric catalog。
- `metric_catalog.json`：指标定义和安全含义。
- `performance_metrics.json`：检测、聚类、建模、重训、窗口处理耗时。
- `trident_performance_benchmark.json/md`：benchmark 模式下的性能报告。
- `learner_network_topology.json`：按学习器聚合的网络拓扑。
- `learner_topology_metric_audit.json`：学习器拓扑指标审计。
- `debug_true_overlap_pairs.csv` / `debug_true_overlap_summary.json` / `learner_true_overlap_network.png`：debug overlap 开启时输出学习器重叠接受关系。
- `learner_aggregated_distribution.csv` / `learner_aggregation_mapping.csv` / `learner_aggregation_summary.json`：overlap 聚合开启时输出聚合学习器结果。
- `decision_tree_*` 相关产物：当 `decision_tree.enabled=true` 时生成解释型规则/分析报告。

### 5.4 live flush

当 `visualization.live_flush_enabled=true` 或 Redis 输入下为 `auto` 时：

- `live_run_status.json` 会在运行中反复更新，结束时写 `finished`。
- `learner_count_over_time.csv` 可在窗口完成后增量刷新。
- `learner_label_distribution.csv` 和 `learner_topology_metric_audit.json` 可按窗口间隔刷新，用于 live 可视化。

## 6. Redis 数据流细节

### 6.1 CSV 注入 Redis

`inject_csv_to_redis()` 数据路径：

```text
CSV
  -> pd.read_csv(nrows=max_rows)
  -> 每行转 dict
  -> 加 event_type=cic_flow
  -> Timestamp 同步到 timestamp 字段
  -> json.dumps()
  -> Redis XADD stream
```

`clear_stream=true` 时会先删除目标 stream。

### 6.2 Redis 读取

有限批读取：

```text
load_redis_flows()
  -> _stream_messages() / _list_messages()
  -> normalize_flow_record()
  -> _records_to_dataframe()
```

流式窗口读取：

```text
iter_redis_flow_windows()
  -> 为本次 perf stream 创建 consumer group
  -> 每次 load_redis_flows(max_messages=window_size)
  -> yield DataFrame
  -> 无数据或 idle timeout 后结束
```

## 7. E2E 压测数据链路

入口是：

```bash
python3 -m trident_demo.stress trident_demo/stress/configs/e2e.yaml
```

核心文件是 `stress/controller.py`。

### 7.1 压测主链路

```text
stress YAML
  -> load_config()
  -> preflight()
  -> docker compose up redis / suricata
  -> 清 Redis Stream
  -> 写入本轮 trident_config.yaml
  -> 后台启动 Trident benchmark 线程
  -> tcpreplay 回放 pcap
  -> Suricata 解析流量并写 Redis Stream
  -> Trident 从 Redis Stream 消费 cic_flow
  -> 等待 Suricata 收敛
  -> 汇总 Redis / Docker / Suricata / Trident 指标
  -> testing/outputs/stress/<run_id>/
```

### 7.2 压测监控与产物

压测期间：

- `sample_redis()` 周期采样 Redis `XLEN`、内存、ops、网络吞吐，写入 `redis_metrics.json`。
- `sample_docker()` 周期采样 Redis 和 Suricata 容器的 `docker stats`，写入 `docker_metrics.json`。
- `run_replay_until_load()` 多轮执行 `tcpreplay`，直到满足最小回放时间和最小 stream 长度。
- `wait_for_suricata_settle()` 根据 Redis Stream 增长速率判断 Suricata 是否进入稳定状态。
- `run_trident_thread()` 在后台调用普通 `run_pipeline()`，但强制 `skip_docker=True`、`no_inject=True`，从本轮 Redis Stream 消费。

压测输出目录：`trident_demo/testing/outputs/stress/<run_id>/`。

主要产物：

- `stress_config_resolved.yaml`：解析后的压测配置。
- `trident_config.yaml`：本轮动态生成的 Trident 配置。
- `workload_manifest.json`：pcap、stream、容器名等元信息。
- `redis_metrics.json`：Redis 采样。
- `docker_metrics.json`：容器资源采样。
- `suricata_metrics.json`：Suricata 容器与日志情况。
- `replay.log`：tcpreplay 输出。
- `suricata.log` / `stats.log`：从 compose logs 目录复制。
- `stress_summary.json` / `stress_summary.md`：最终汇总。
- `trident/<trident_run_id>/...`：嵌套的 Trident benchmark 产物。
- `trident_run_dir.txt`：嵌套 Trident 输出目录。

### 7.3 压测指标汇总

`build_component_metrics()` 将各来源指标汇总为：

- `suricata`：回放前后 stream 长度、回放期/尾部/总流量速率、容器 CPU/内存。
- `trident`：分析耗时、pipeline 耗时、线程运行时长、纯推理 FPS、窗口处理 FPS、等待占比、CPU/GPU/内存资源。
- `redis`：最大/最终 XLEN、峰值内存。

`build_derived_timing()` 补充：

- `replay_send_total_seconds`
- `suricata_parse_total_seconds`
- `trident_analysis_total_seconds`
- `trident_pipeline_total_seconds`
- `trident_thread_runtime_seconds`

## 8. 前端展示数据流

前端目录是 `trident_demo/frontend/visualize/`，使用 Vite + React。

当前前端主要展示 E2E 压测数据：

```text
浏览器
  -> /api/stress-runs
  -> vite.stressDataPlugin.ts
  -> 读取 trident_demo/testing/outputs/stress/*
  -> App.tsx 渲染指标卡、历史列表、阶段耗时和时序数据
```

API 逻辑：

- `GET /api/stress-runs`：
  - 扫描 `testing/outputs/stress/` 下包含 `stress_summary.json` 的目录。
  - 返回 run 列表和最新 run id。
- `GET /api/stress-runs/<run_id>`：
  - 读取 `stress_summary.json`、`redis_metrics.json`、`docker_metrics.json`、`suricata_metrics.json`。
  - 如果有 `trident_run_dir`，读取其中的 `trident_performance_benchmark.json`。
  - 解析 `replay.log` 中的 packets、bytes、seconds、Mbps、flows。

前端计算展示：

- 回放线速 GB/s。
- 总发送流量。
- Trident 纯推理速度、窗口处理速度、联机有效速度。
- Suricata 输出速率、输入积压速度差。
- Trident 计算占空比、等待占比、CPU/GPU/内存。
- 历史压测 run 对比表。

## 9. 处理速度分析

当前 demo 中“速度”不是单一指标，而是按数据链路拆成多个口径。分析时需要先确认正在看哪一段耗时，否则容易把 Suricata 出流等待、Redis 拉流等待、Trident 纯计算和最终导出混在一起。

### 9.1 普通 Trident run 的速度口径

普通 `batch/replay/benchmark` run 中，耗时主要由 `PerformanceRecorder` 和 `TridentStreamingExperiment.perf_stats` 记录。

核心阶段：

```text
pipeline_total
  -> pipeline_preflight
  -> pipeline_redis_inject
  -> pipeline_experiment
       -> io_load_total
          -> io_source_read
          -> io_preprocess
          -> io_feature_matrix
       -> init_learners
       -> stream_inference
       -> stream_cluster
       -> stream_create_learner
       -> stream_retrain
       -> export_dataset_profile
       -> export_run_artifacts
       -> export_visualization
  -> pipeline_postrun
```

主要速度指标：

- `flows_per_second_inference`：只看流式推理阶段，通常是评估 Trident 检测核心能力的主指标。
- `flows_per_second_end_to_end`：从 pipeline 总耗时角度计算，包含加载、预处理、初始化、推理、聚类、导出等开销。
- `avg_detect_seconds_per_window`：平均每个窗口的模型分类耗时。
- `avg_cluster_seconds_per_window`：平均每个窗口 unknown 聚类耗时。
- `avg_create_learner_seconds_per_window`：平均每个窗口新学习器创建耗时。
- `avg_window_seconds` 或 `avg_window_total_seconds_per_window`：窗口内检测、聚类、建模、重训的总耗时。

常用公式：

```text
stream_flow_count = rows_used - init_rows

纯推理速度 =
  stream_flow_count / detect_seconds_total

窗口处理速度 =
  stream_flow_count / window_total_seconds_total

端到端速度 =
  flow_count / pipeline_total
```

解释：

- `纯推理速度` 排除了初始化学习器、聚类建模、重训、导出等开销，适合回答“模型分类本身能跑多快”。
- `窗口处理速度` 包含推理、unknown 聚类、新建学习器、增量重训，是更接近在线算法计算成本的指标。
- `端到端速度` 包含 IO 和导出，适合评估一次完整 demo run 的总成本，但不适合作为模型吞吐上限。

### 9.2 Redis / benchmark 模式下的速度口径

`replay` 和 `benchmark` 从 Redis Stream 读取数据。这里速度可能受 Redis 等待、stream 中已有数据量、`idle_timeout_seconds`、`max_messages` 影响。

数据读取速度相关阶段：

- `io_source_read`：从 Redis 拉取消息并解析为 DataFrame。
- `io_preprocess`：时间、标签、缺失值、过滤等处理。
- `io_feature_matrix`：数值特征选择和矩阵构建。

如果 Redis Stream 中数据已经完整存在，那么 `io_source_read` 更接近批量拉取性能；如果 Trident 与 Suricata 并行运行，则 `io_source_read` 和 `pipeline_experiment` 可能包含等待上游产生新 flow 的时间。

分析建议：

- 看 Trident 核心能力：优先用 `flows_per_second_inference`。
- 看在线窗口处理能力：看 `stream_flow_count / window_total_seconds_total`。
- 看 Redis 拉流是否拖慢：比较 `io_source_read` 与 `stream_window_total`。
- 看导出是否拖慢：比较 `export_run_artifacts`、`export_visualization` 与 `pipeline_total`。

### 9.3 perf_mode 的速度分析

E2E 压测中可以启用 `runtime.perf_mode=true`。该模式会走 `_run_perf_mode_redis_stream()`，目的是减少非核心导出对性能数据的干扰。

perf_mode 的特点：

- 从 Redis 按窗口连续消费，不先完整 drain 全部数据。
- 第一批窗口用于初始化学习器。
- 跳过 dataset profile、拓扑、metric audit、decision tree 等重导出。
- 只保留最小性能产物，例如 `learner_count_over_time.csv`、`performance_summary.json`、`trident_performance_benchmark.json/md`。

适用场景：

- 评估 Trident 在线处理吞吐。
- 排除可视化和画像导出的影响。
- 对比不同 `window_size`、模型后端、GPU/CPU、是否创建新学习器的性能差异。

不适用场景：

- 分析最终学习器画像完整性。
- 分析拓扑、metric audit、decision tree 产物。
- 做完整演示产物验收。

### 9.4 E2E 压测的速度口径

E2E 压测链路是：

```text
tcpreplay -> Suricata -> Redis Stream -> Trident
```

这里至少有三类速度：

#### 9.4.1 回放线速

来源：

- `replay.log`
- 前端 `parseReplayStats()` 解析 `Rated: ... Mbps`

含义：

- pcap 发送到网卡的速度。
- 这是输入流量压力，不等于 Suricata 产出 flow 的速度，也不等于 Trident 处理速度。

换算：

```text
回放 GB/s = rated_mbps_avg / 8000
```

#### 9.4.2 Suricata 产出速度

来源：

- Redis Stream 长度变化 `XLEN`
- `wait_for_suricata_settle()`
- `build_component_metrics().suricata`

主要字段：

- `flow_delta_replay`：tcpreplay 回放阶段 Redis Stream 增长量。
- `flow_delta_settle`：回放后等待阶段 Redis Stream 继续增长量。
- `flow_delta_total`：整轮 Suricata 产生的 flow 数。
- `flow_fps_replay_only`：回放阶段 flow/s。
- `flow_fps_tail_only`：回放后尾部解析阶段 flow/s。
- `flow_fps_total`：回放 + 收敛阶段综合 flow/s。

注意：

- Suricata 的 flow 输出受流超时、会话结束、内部 buffer、Redis 写入影响。
- pcap 已经回放完成，不代表 Suricata 已经把所有 flow 写入 Redis。
- 所以 `flow_fps_total` 适合看上游供给趋势，不适合作为 Trident 算力指标。

#### 9.4.3 Trident 处理速度

来源：

- 嵌套 Trident run 的 `trident_performance_benchmark.json`
- `stress_summary.json.derived_component_metrics.trident`

主要字段：

- `reported_fps_inference`：benchmark 报告中的纯推理 flow/s。
- `stream_window_fps`：窗口处理 flow/s。
- `runtime_fps_true`：Trident 线程运行期真实 flow/s，包含等待上游数据。
- `analysis_fps_true`：按离散分析阶段求和得到的 flow/s。
- `pipeline_fps_true`：按 Trident pipeline 总耗时计算的 flow/s。
- `compute_duty_cycle`：计算占空比。
- `wait_ratio`：等待占比。

推荐阅读顺序：

1. `reported_fps_inference`：判断模型推理上限。
2. `stream_window_fps`：判断在线算法窗口计算能力。
3. `runtime_fps_true`：判断 Trident 在真实并行压测中的有效速度。
4. `wait_ratio`：判断低 `runtime_fps_true` 是否由等待上游流量造成。
5. `pipeline_fps_true`：判断完整 Trident run 的总成本。

#### 9.4.4 等待时间分解

你提到的“还有一些等待时间”，在这套 demo 里确实存在，而且它们通常不是纯计算时间，而是链路等待时间。结合 `stress_summary.json`、`derived_timing` 和 `trident_performance_benchmark.json`，可以拆成下面几类。

##### A. 压测编排等待

这些等待发生在 `trident_demo/stress/controller.py` 的外层，不属于 Trident 模型本身。

- `preflight`：检查 Docker、Redis、Suricata 镜像、共享库、pcap、配置。
- `start_services`：启动 Redis 和 Suricata 容器。
- `baseline`：压测前采样空载基线。
- `tcpreplay`：回放 pcap 的实际发送时间。
- `wait_after_replay`：等待 Suricata 把尾部流量继续解析并写入 Redis。

其中最典型的“等待”是 `wait_after_replay`，它对应 `derived_timing.suricata_parse_total_seconds`。它不是 tcpreplay 的发送时间，而是 Suricata 在回放结束后继续收尾解析、把最后一批 flow 写入 Redis 的时间。

##### B. Trident 启动等待

这些等待发生在 Trident 进入在线处理前后。

- 初始化段等待：系统必须先凑够 `stream.init_ratio` 指定的初始化区间，才能构建初始学习器。
- `init_known_mode=benign_only` 时，还要等到足够多的良性样本出现。
- 如果配置了 `init_benign_year` 或 `init_benign_count`，还会进一步等到满足这些约束。

这类等待会体现在 `init_learners` 之前的数据积累阶段，不一定单独以一个 stage 名字出现，但会让“第一批可推理窗口”启动得更晚。

##### C. 窗口凑齐等待

这是 Redis 流式处理里最常见的等待。

Trident 的窗口不是按时间截断，而是按样本数截断，所以在窗口没有攒满之前，会出现“等数据”的时间：

- `stream.window_size` 还没凑够。
- Redis Stream 还没写入足够消息。
- `load_redis_flows()` 或 `iter_redis_flow_windows()` 还在等待 `block_timeout_seconds`、`idle_timeout_seconds`、`wait_for_target_seconds`。

这一类等待在 `perf_mode` 中尤其重要，因为它直接影响 `runtime_fps_true` 和 `wait_ratio`。

##### D. Trident 在线链路等待

即使数据已经到了，Trident 仍然可能因为自己的处理节奏出现等待或空转。

常见来源：

- `stream_inference` 之外的聚类和建模必须按窗口执行。
- `TMagnifier` 要等 unknown buffer 达到 `cluster_trigger_size` 才会真正做 DBSCAN。
- `TSieve` 的增量更新要等某个学习器累计到 `increment_min_samples`，或者满足 `increment_use_last_train_gap`。
- 新学习器可能还会受 `new_learner_cooldown_windows` 影响，短时间内不能立刻继续训练。

这些不是 CPU 空闲等待，而是“算法上必须等到条件满足”的时间。

##### E. Redis 读取等待

普通 Redis 模式会先 drain 一批数据，但读取过程仍可能包含等待：

- `block_timeout_seconds`：XREAD / BLPOP 的阻塞时间。
- `idle_timeout_seconds`：连续一段时间没新消息时结束读取。
- `wait_for_target_seconds`：在希望等到目标消息数时使用的额外等待。

所以普通 Redis 模式下的 `io_source_read`，有时并不只是“读取速度慢”，还夹杂着“等待上游产出”的时间。

##### F. 导出等待

最后一类是结果导出和收尾等待。

- `export_run_artifacts`
- `export_visualization`
- `pipeline_postrun`

当启用完整可视化、拓扑、metric audit、decision tree 时，这一段会显著变长。它通常不是在线处理瓶颈，但会抬高端到端总耗时。

##### 怎么在结果里识别这些等待

如果看压测结果，可以这样拆：

```text
trident_experiment_seconds
  - stream_window_seconds_total
  - init_seconds_total
  = trident_wait_seconds
```

这就是 `stress/controller.py` 里 `build_component_metrics()` 的口径。它把 Trident 实际在做窗口处理和初始化训练之外的时间，统一归到“等待”里。

因此：

- `wait_ratio` 高，不一定代表 Trident 算得慢。
- 很多时候是上游供给慢，或者窗口条件还没满足。
- `stream_window_fps` 低，才更像是 Trident 自身在线处理能力不足。

### 9.5 前端展示中的速度字段

`frontend/visualize/src/App.tsx` 会把 flow/s 结合 `replay.log` 中的平均 bytes/flow 换算成 GB/s：

```text
GB/s = flow_per_second * avg_bytes_per_flow / 1_000_000_000
```

前端关键卡片含义：

- `回放线速`：tcpreplay 发送速率，来自 Mbps。
- `Trident 纯推理速度`：`reported_fps_inference` 换算 GB/s。
- `Trident 窗口处理速度`：`stream_window_fps` 换算 GB/s。
- `Trident 联机有效速度`：`runtime_fps_true` 换算 GB/s。
- `Trident 计算占空比`：计算耗时在实验总耗时中的占比。
- `等待占比`：Trident 等待上游流量/窗口凑齐的比例。
- `输入积压速度差`：`suricata.flow_fps_total - trident.runtime_fps_true`。

解释：

- `输入积压速度差 > 0`：上游产生 flow 的速度高于 Trident 联机处理速度，可能出现积压。
- `输入积压速度差 < 0`：Trident 有能力追平当前上游输入。
- 如果 `等待占比` 很高，说明 Trident 速度被上游供给限制，不能简单认为 Trident 算力不足。

### 9.6 如何判断瓶颈

可以按下面顺序定位：

```text
1. replay.log 的 rated Mbps 是否达到预期？
   否 -> tcpreplay / 网卡 / pcap 回放瓶颈

2. Redis XLEN 是否持续增长？
   否 -> Suricata 解析或 Redis 写入不足

3. Suricata flow_fps_total 是否大于 Trident runtime_fps_true？
   是 -> 在线链路可能积压

4. Trident wait_ratio 是否很高？
   是 -> Trident 在等上游，不是核心计算瓶颈

5. stream_window_fps 是否明显低于 reported_fps_inference？
   是 -> 聚类、新建学习器、增量重训等窗口附加成本较高

6. pipeline_fps_true 是否明显低于 stream_window_fps？
   是 -> IO、初始化、导出或可视化产物成本较高
```

### 9.7 优化方向

如果瓶颈在 Trident 纯推理：

- 使用 GPU 或确认当前运行没有被 `runtime.cpu_only=true` 限制。
- 调大 batch 相关参数，例如 `tsieve.batch_size`。
- 减少学习器数量，或调整聚合/重聚类策略。
- 考虑 `classifier_backend=iforest` 与 `ae` 的性能差异。

如果瓶颈在窗口处理：

- 调整 `stream.window_size`，减少过小窗口造成的调度成本。
- 提高 `tmagnifier.cluster_trigger_size` 或 `new_class_min_size`，减少频繁聚类/建模。
- 调高 `tsieve.increment_min_samples`，减少增量重训频率。
- 限制 `max_retrain_per_learner` 或降低 `increment_epochs`。

如果瓶颈在导出：

- 压测时启用 `perf_mode=true`。
- 关闭 `visualization.dataset_topology_enabled`、`learner_topology_enabled`、`metric_audit_enabled`。
- 关闭 `decision_tree.enabled`。
- 降低 `metric_audit_max_learners`。

如果瓶颈在 Redis / Suricata：

- 看 `redis_metrics.json` 的 `xlen`、内存、ops 曲线。
- 看 `docker_metrics.json` 中 Redis/Suricata CPU 和内存。
- 看 `suricata.log`、`stats.log` 是否有解析、丢包、输出错误。
- 区分 tcpreplay 发送速度和 Suricata flow 输出速度。

## 10. 数据处理主干图

```text
                         +-------------------+
                         | CLI / stress CLI  |
                         +---------+---------+
                                   |
             +---------------------+----------------------+
             |                                            |
      普通 run profiles                              E2E stress
             |                                            |
   +---------+---------+                         +--------+---------+
   | batch / viz-demo  |                         | tcpreplay pcap   |
   | CSV 输入          |                         +--------+---------+
   +---------+---------+                                  |
             |                                      Suricata CIC
   +---------v---------+                                  |
   | 数据准备/CSV读取  |                                  v
   +---------+---------+                         Redis Stream cic_flow
             |                                            |
             +---------------------+----------------------+
                                   |
                          load_redis_flows / CSV DataFrame
                                   |
                          时间、标签、缺失值、过滤
                                   |
                              特征矩阵 x_all
                                   |
                         初始 tSieve 学习器
                                   |
                         按 window 流式处理
                                   |
          +------------------------+------------------------+
          |                        |                        |
     已知学习器接受            UNKNOWN buffer          运行指标记录
          |                        |                        |
      增量更新              DBSCAN 聚类 -> NEW_*          |
          |                        |                        |
          +------------------------+------------------------+
                                   |
                              产物导出
                                   |
        +--------------------------+--------------------------+
        |                          |                          |
   outputs/<run_id>          testing/outputs/stress/<run_id>       visualize API
```

## 11. 关键文件索引

- 入口：`trident_demo/cli.py`、`trident_demo/__main__.py`
- profile 编排：`trident_demo/pipeline/runner.py`
- 上下文：`trident_demo/pipeline/context.py`
- 实验主流程：`trident_demo/pipeline/experiment.py`
- Redis 输入：`trident_demo/io/redis_loader.py`
- CSV 注入 Redis：`trident_demo/orchestration/redis_inject.py`
- viz-demo 数据准备：`trident_demo/orchestration/data_prep.py`、`trident_demo/orchestration/viz_data_prep.py`
- 核心模型：`trident_demo/core/tsieve.py`、`trident_demo/core/tscissors.py`、`trident_demo/core/tmagnifier.py`
- 可视化导出：`trident_demo/export/visualization.py`、`trident_demo/export/dataset_topology.py`、`trident_demo/export/live_flush.py`
- 压测：`trident_demo/stress/controller.py`
- 前端 API：`trident_demo/frontend/visualize/vite.stressDataPlugin.ts`
- 前端 UI：`trident_demo/frontend/visualize/src/App.tsx`
