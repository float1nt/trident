# Trident Demo — 单入口全流程

`trident_demo/` 是与原 `trident_stream/` **完全解耦**的 Demo 栈：代码为复制 + 重组，**不 import** 旧模块。

## 一条命令跑通

```bash
# CSV 离线（替代 main.py）
python3 -m trident_demo run --profile batch

# Redis 直接接入（读取已有 suricata:cic_flow stream）
python3 -m trident_demo run --profile replay --max-rows 10000

# Redis 直接接入 + 性能 benchmark
python3 -m trident_demo run --profile benchmark --max-rows 10000

# Viz demo：数据准备 + 跑实验（替代 learner_qualification/run_aligned_viz_pipeline.sh）
python3 -m trident_demo run --profile viz-demo

# 独立 E2E 压测：tcpreplay → Suricata → Redis → Trident demo benchmark
python3 -m trident_demo.stress trident_demo/stress/configs/e2e.yaml
```

## 常用选项

| 选项 | 说明 |
|------|------|
| `--config PATH` | 覆盖默认 `trident_demo/configs/<profile>.yaml` |
| `--max-rows N` | 限制加载/注入行数 |
| `--benchmark` | 开启 `performance_benchmark`（`benchmark` profile 默认开启） |
| `--skip-docker` | replay：不自动 `docker compose up redis` |
| `--no-inject` | replay / benchmark：跳过 CSV→Redis 注入 |
| `--output-dir PATH` | 产物根目录（默认 `trident_demo/outputs`） |

`replay` 和 `benchmark` 默认直接从 Redis stream 读取数据，不做 CSV 注入。
如果要恢复“静态 CSV 回放到 Redis 再跑”的模式，在配置文件的 `inject.enabled` 改为 `true`。

## 产物

每次 run 写入 `trident_demo/outputs/<run_id>/`，包括：

- `run_summary.txt`、`sample_assignments.csv`
- `learner_topology_metric_audit.json`（含 `reference_rules`）
- `trident_performance_benchmark.json`（benchmark profile，包含 pipeline / Redis / experiment / export 阶段）
- `live_run_status.json`（replay / Redis 流式）

可视化：`cd visualize && npm run dev`，选择对应 run_id。

## E2E 压测

压测逻辑单独放在 `trident_demo/stress/`，结果单独写入
`trident_demo/stress_outputs/<run_id>/`，不混入普通 demo run。

入口：

```bash
python3 -m trident_demo.stress trident_demo/stress/configs/e2e.yaml
```

压测脚本不会构建 Suricata 镜像，只会验证 `suricata-cic-live:local`
存在且动态库完整。每轮会强制重建 Suricata 容器以刷新 `IFACE` 和
`REDIS_STREAM`，然后并行运行 Trident benchmark 与 `tcpreplay`。

主要产物：

- `stress_summary.json` / `stress_summary.md`
- `redis_metrics.json`、`docker_metrics.json`、`suricata_metrics.json`
- `replay.log`、`commands.log`
- `suricata.log`、`stats.log`
- `trident/<trident_run_id>/trident_performance_benchmark.json`

## 架构

```
cli.py (--profile)
  → orchestration/   Preflight → optional Inject → DataPrep(viz-demo)
  → pipeline/stages/ TridentStreamingExperiment.run()
  → orchestration/postrun.py
```

## 解耦检查

```bash
bash trident_demo/check_decoupling.sh
```

## 与 Legacy 对照

| Legacy | Demo |
|--------|------|
| `python3 main.py --config configs/config.yaml` | `python3 -m trident_demo run --profile batch` |
| `python3 scripts/benchmark_trident_performance.py` | `python3 -m trident_demo run --profile benchmark` |
| `bash scripts/run_static_suricata_redis_benchmark.sh` | `python3 -m trident_demo run --profile replay --config <inject.enabled=true 的配置>` |
| `bash learner_qualification/run_aligned_viz_pipeline.sh` | `python3 -m trident_demo run --profile viz-demo` |
