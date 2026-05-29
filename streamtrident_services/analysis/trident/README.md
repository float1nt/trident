# Trident Service

独立 Trident 服务目录。

当前阶段默认实现 Redis list 到 ClickHouse `ch_flow` 的实时有损消费、窗口判定、assignment 回写、learner/snapshot 持久化、Redis 输出流发布和只读 API。

服务边界：

- 不 import `trident_demo`
- 不 import sibling `suricata/` 或 `redis/` 服务代码
- Redis list/stream 字段协议通过 `config/trident.yaml` 和 loader 归一化对齐

## Worker

```bash
cd streamtrident_services/analysis/trident
pip install -r requirements.txt
python -m app.migrate --config config/trident.yaml
python -m app.worker --config config/trident.yaml --once
```

### 冷启动 / 推理双模式

worker 支持显式运行模式：

```bash
python -m app.worker --config config/trident.yaml --mode cold_start
python -m app.worker --config config/trident.yaml --mode inference
```

本地开发时也可以使用 analysis 侧脚本：

```bash
../scripts/start-worker-coldstart.sh
../scripts/start-worker-inference.sh
```

语义：

- `cold_start`：只用于良性流量建模，允许空 learner 起步，创建 `COLD_*|BENIGN`。学习稳定后 finalize session，写入 `pg_session_runtime`，并对全部 `COLD_*|BENIGN` 做一次固定良性 audit 作为冷启动产物。
- `inference`：纯推理。启动时要求同一 `session_id` 已有 finalized cold start 和可加载的 `COLD_*|BENIGN`。推理阶段不创建 `0000|UNLABELED`，不创建 `COLD_*|BENIGN`，未知聚类只创建 `NEW_*`。
- 冷启动结束后，`COLD_*|BENIGN` 在 inference 中视为普通已加载学习器；不做固定良性保护，也不改变当前 TSieve “非 BENIGN 优先”的匹配策略。

常用流程：

```bash
../scripts/start-worker-coldstart.sh    # 注入良性流，等待日志 cold_start_complete
../scripts/start-worker-inference.sh    # 同 session_id 下启动推理/攻击评估
```

worker 会：

- 默认使用 Redis list pop 读取 `suricata:cic_flow`，取走即从 Redis 删除
- 按 `list_maxlen` 裁剪积压，保留最新一段实时缓冲
- 归一化 flow 字段
- 按窗口执行在线引擎，产生 accepted / unknown / new learner / metrics
- 写入 `ch_flow` 的 `assigned` 版本
- upsert `pg_learner` 并追加 `pg_learner_snapshot`
- 输出 `trident:assignments`、`trident:alerts`、`trident:metrics`

当前在线引擎已经复刻 `trident_demo/core` 的核心实时算法逻辑，但代码位于本服务内，不 import demo：

- `tSieve`：AutoEncoder / IsolationForest one-class learner、batch classify、非 BENIGN 优先、增量训练
- `tScissors`：POT/EVT 阈值估计和分位数 fallback
- `tMagnifier`：unknown buffer、DBSCAN 聚类、新 learner 创建

learner 的 scaler、模型参数、阈值和 feature schema 会序列化进 `pg_learner.profile_json`，worker 重启后可以从当前态恢复 learner。

在线质量增强：

- BENIGN confidence filter：BENIGN learner 的 accepted 样本必须足够低损失才进入增量训练
- Cluster purity gate：unknown cluster 升级新 learner 前检查 BENIGN 接收率，失败时回灌 unknown buffer
- Increment route gate：增量训练前检查样本对目标 learner 的 margin 和相对其他 learner 的优势
- Increment IsolationForest guard：对增量训练样本做二次离群过滤
- Drift gate：历史样本与新样本差异不足时跳过重训
- Small learner recluster：周期性销毁样本量过小的 `NEW_*` learner，并把历史样本回灌 unknown 重新聚类
- History pool sampling：每个 learner 维护历史样本池，增量训练混入历史样本以降低遗忘
- Learner audit / topology / reference rules：写入 `metric_json`、`topology_json`、`rule_json` 和 `risk_*`

预处理：

- 按 `compact_stats_no_env` / `stable_stats_no_env` 对齐 CIC 数值特征列
- 处理 `Flow Bytes/s` 的 inf/NaN 并写入 `flow_bytes_s_missing_flag`
- 处理 `FWD Init Win Bytes` / `Bwd Init Win Bytes` 的 `-1` sentinel 并写入 missing flag
- 写入 `is_non_tcp`
- `preprocessing_drop_all_zero` 默认关闭，避免上游非标准字段被误删；需要严格过滤时可打开

模型状态：

- learner 的 scaler / AE / IsolationForest 主体保存到 `model_store_dir`
- `pg_learner.profile_json` 和 snapshot 只保存 `model_ref` 路径、阈值、feature schema 和质量门控元数据

运维 metrics：

- 每窗口写入 `trident:metrics`
- 包含 ingest/engine/snapshot/assignment/output/ack/window 总耗时
- 包含 Redis `XLEN`、pending、读入数、写入数、assignment 数
- 包含 learner 数、unknown buffer、gate stats、进程 CPU/RSS 和 loadavg

未接入 demo 的 overlap debug 和离线可视化 artifact 导出；服务侧通过数据库/API/Redis 输出提供运行结果。

## API

```bash
cd streamtrident_services/analysis/trident
python -m app.api --config config/trident.yaml --host 127.0.0.1 --port 8090
```

最小接口：

- `GET /api/v1/health`
- `GET /api/v1/runtime/summary`
- `GET /api/v1/flows`
- `GET /api/v1/learners`
- `GET /api/v1/learners/{learner_name}`
- `GET /api/v1/learners/{learner_name}/flows`
