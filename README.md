# Trident Streaming AE（CICIDS2017）

这个项目实现了一个简化版的流式异常检测与新类发现流程，核心思想是：

- 已知类：用一类自编码器（AE）建模
- 阈值判定：用 EVT（POT）估计重构误差阈值
- 未知发现：把未知样本缓冲后聚类，满足条件则新增学习器

当前默认数据源是 `data/` 下的 CICIDS2017 按天 CSV（周一到周五）。

## 目录结构

- `main.py`：入口脚本
- `stream_trident_ae.py`：兼容旧命令的别名入口（内部转发到 `main.py`）
- `configs/`：配置文件目录（如 `configs/config.yaml`）
- `learner_qualification/`：学习器定性与可视化 artifact 导出入口（见 `learner_qualification/README.md`）
- `scripts/`：离线研究/数据准备脚本；入口和分类见 `scripts/README.md`
- `trident_stream/experiment.py`：主流程（加载数据、流式循环、输出结果）
- `trident_stream/tsieve.py`：tSieve（AE 学习器管理、分类、增量更新）
- `trident_stream/tscissors.py`：tScissors（EVT 阈值估计）
- `trident_stream/tmagnifier.py`：tMagnifier（未知样本聚类与新类提议）
- `outputs/`：运行结果目录（日志、CSV、图、摘要）

## 运行方式

在项目根目录执行：

```bash
python3 main.py --config configs/config.yaml
```

运行时会同时输出到终端和 `outputs/run.log`。

每次 run 会在 `outputs/runs/<run_id>/` 写出 `visualize/` 所需产物。旧 run
需要补导出时使用：

```bash
python3 learner_qualification/export_visualization_artifacts.py outputs/runs/<run_id>
```

## 2017→2019 迁移测试（同义列对齐）

先生成对齐后的统一特征数据（基于人工同义列映射）：

```bash
python3 scripts/align_cic2017_2019.py --data-root data --out-dir data/aligned_2017_2019
```

再运行迁移实验（由 `configs/config.yaml` 的 `input_files` 控制先 2017 后 2019）：

```bash
python3 main.py --config configs/config.yaml
```

对齐映射与保留列会写到 `data/aligned_2017_2019/alignment_report.json`。

## 配置说明（`configs/config.yaml`）

### 1) 数据与输出

- `paths.data_dir`：数据目录（默认 `data`）
- `paths.input_files`：读取顺序（当前为周一到周五）
- `paths.output_dir`：输出目录（默认 `outputs`）
- `paths.log_file`：日志文件名（默认 `run.log`）
- `input.source`：数据源类型，默认 `csv`；设为 `redis` 时从 Redis 队列/Stream 拉取有限批量流记录后复用同一条 Trident 全流程
- `input.redis.*`：Redis 输入配置，已对齐根目录 `suricata-cic-redis-live` 的默认 Redis Stream：`key=suricata:cic_flow`、`event_type=cic_flow`；也支持 `data_structure: list`。常用字段包括 `url`、`key`、`max_messages`、`idle_timeout_seconds`、`default_label`；Redis 输入默认跳过 `year_include`/攻击类型采样等离线数据集过滤，需复用这些过滤时显式设置 `apply_runtime_filters: true`。Live 流没有真值标签时，`allow_unlabeled_initial_learner: true` 会在没有 BENIGN 冷启动样本时用未标注流建立初始学习器。
- `visualization.live_flush_*`：流式运行期间将产物**增量写入磁盘**（`outputs/runs/<run_id>/`），包括 `learner_count_over_time.csv`、`learner_topology_metric_audit.json`（含规则层 `reference_rules`）、`learner_label_distribution.csv`、`live_run_status.json`。`live_flush_enabled: auto` 在 `input.source=redis` 时自动开启。

### 实时可视化（磁盘产物）

1. Trident 运行时产物始终落在 `outputs/runs/<run_id>/`（与历史 Run 相同路径）。
2. 流式场景下按窗口增量刷新上述文件；Run 结束写入 `live_run_status.json`（`status: finished`）。
3. 在 `visualize/` 启动前端：`npm run dev`，打开 **实时监控**（`/live-monitor`）或 **学习器详情 → 实时模式**（`?live=1`）。
4. Vite 开发服务器通过 SSE（`/api/live/events`）轮询磁盘文件变更并推送到浏览器；也可设置 `TRIDENT_LIVE_ARTIFACTS_ENABLED=1` 强制开启。

### 2) 运行控制

- `runtime.seed`：随机种子（当前为 42）
- `runtime.cpu_only`：`false` 时优先 CUDA，`true` 强制 CPU
- `runtime.max_rows`：最大读取行数；`0` 表示不截断
- `runtime.year_include`：年份白名单（如 `["2017","2019"]`）
- `runtime.attack_type_include` / `runtime.attack_type_exclude`：攻击类型白/黑名单（基于 `Label`）
- `runtime.protocol_include`：协议白名单（支持 `tcp`/`udp`/`other` 或协议号如 `6`/`17`）

### 3) 可视化产物

- `visualization.metric_audit_min_samples`：学习器拓扑指标审计的最小流数
- `visualization.metric_audit_max_learners`：学习器拓扑指标审计最多输出的学习器数
- `dataset_network_topology.json`、`learner_network_topology.json`、
  `learner_topology_metric_audit.json` 会随 run 自动落盘

### 4) 流式阶段

- `stream.init_ratio`：前多少比例数据用于初始学习器
- `stream.init_known_mode`：
  - `benign_only`：仅 BENIGN 建初始学习器
  - `all_init_labels`：初始阶段出现的所有标签都可建学习器
- `stream.window_size`：每个窗口处理的样本数

### 5) 三个核心组件参数

- `tsieve.*`：AE 训练、增量更新、最小样本要求等
- `tscissors.*`：EVT 参数（`evt_quantile`、`evt_risk`、`fallback_quantile`）
- `tmagnifier.*`：未知缓冲触发、DBSCAN 聚类参数、新类最小簇大小

## 主流程（端到端）

1. **读取并拼接数据**
   - 按 `input_files` 顺序读取
   - 转换 `Timestamp`、按时间排序
   - 特征预处理（去掉非数值或标识列，处理 NaN/Inf）
2. **初始化学习器**
   - 取前 `init_ratio` 数据作为冷启动阶段
   - 按配置构建初始学习器（常用 `BENIGN`）
3. **流式窗口循环**
   - 每个窗口内逐样本判别：
     - 被某个学习器接受 -> 记为该类
     - 无人接受 -> 进入未知缓冲区
   - 窗口末尾对未知缓冲聚类：
     - 发现稳定大簇 -> 新增学习器（`NEW_x`）
   - 对已有学习器做增量更新并刷新阈值
4. **落盘结果**
   - `learner_count_over_time.csv`
   - `learner_count_over_time.png`
   - `run_summary.txt`
   - `run.log`

## 日志如何看

常见日志字段：

- `Device: cuda/cpu`：当前设备
- `[Init] learner=...`：初始学习器建立成功
- `[Window] ... learners=N unknown_buffer=M`：
  - `learners`：当前学习器数量
  - `unknown_buffer`：未知样本缓冲区长度
- `[NewLearner] NEW_k`：发现新类并新增学习器

## 输出文件解释

- `outputs/run_summary.txt`
  - `total_windows`：窗口总数
  - `initial_learner_count`：初始窗口学习器数
  - `final_learner_count`：结束时学习器数
  - `rows_used`：实际参与处理的数据行数
- `outputs/learner_count_over_time.csv`
  - 每行是一个窗口结束时刻的快照
- `outputs/learner_count_over_time.png`
  - 学习器数随时间变化曲线（同一 y 值可连续出现多次，表示多个窗口数量未变化）

## 常见问题

### Q1：为什么 `rows_used` 比预期少？

常见原因：

- `input_files` 只配了部分天数
- `max_rows` 非 0 导致截断
- 时间戳无效行会被丢弃

### Q2：为什么每次结果不完全一样？

已设置随机种子（`runtime.seed`），但在 GPU 上个别算子可能仍有轻微非确定性。若需要更严格复现，可在代码中额外开启 PyTorch 确定性设置。

### Q3：图上“一个点出现多次”是 bug 吗？

不是。每个点对应一个窗口快照；如果连续多个窗口 `learner_count` 相同，就会在同一水平高度出现多个点。
