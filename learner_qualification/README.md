# 学习器定性（Learner Qualification）

本目录承载 **run → `outputs/runs/<run_id>` → visualize** 正式链路中与学习器拓扑、指标审计、规则语义相关的**产品化入口**。

可复用计算逻辑在 `trident_stream/`（`visualization_artifacts.py`、`learner_metric_audit.py`、`metric_audit_catalog.py`、`dataset_topology.py`）；本目录只保留**命令行入口与 shell 编排**，与 `scripts/` 中的离线研究、HPO、特征搜索等脚本分离。

## 数据流

```text
main.py
  -> TridentStreamingExperiment.run()
  -> outputs/runs/<run_id>/
       - dataset_network_topology.json
       - learner_network_topology.json
       - learner_topology_metric_audit.json
  -> visualize/ 读取 run 目录
```

run 结束时由 `trident_stream.visualization_artifacts.export_visualization_artifacts` 自动落盘；旧 run 用本目录统一补导出。

详细整理记录见 [ARTIFACT_PIPELINE.md](./ARTIFACT_PIPELINE.md)。定性方案见项目根目录 [LEARNER_QUALIFICATION_SCHEME.md](../LEARNER_QUALIFICATION_SCHEME.md)。

## 稳定入口

| 任务 | 命令 |
| --- | --- |
| 正常运行 Trident（产物自动写出） | `python3 main.py --config configs/config.yaml` |
| 为旧 run 重建三类可视化 artifact | `python3 learner_qualification/export_visualization_artifacts.py outputs/runs/<run_id>` |
| 同上（shell 包装，可选 run 目录） | `bash learner_qualification/finish_viz_exports.sh [outputs/runs/<run_id>]` |
| 对齐 demo 数据 + 跑 viz 实验配置 | `bash learner_qualification/run_aligned_viz_pipeline.sh` |

## 细粒度导出（调试 / 旧笔记）

| 脚本 | 作用 |
| --- | --- |
| `export_dataset_network_topology.py` | 仅 `dataset_network_topology.json` |
| `export_learner_network_topology.py` | 仅 `learner_network_topology.json` |
| `export_learner_topology_metric_audit.py` | 仅 `learner_topology_metric_audit.json`（支持 `--raw-csvs` 直读 CSV） |

修复页面空数据时，**优先**使用 `export_visualization_artifacts.py`，避免漏写某一类 JSON。

## 离线评估（非页面必需）

| 脚本 | 作用 |
| --- | --- |
| `analyze_learner_internal_topology.py` | 学习器内拓扑特征对 attack/benign 学习器的 AUC 分离度报告 |
| `analyze_learner_behavior_metrics.py` | 基于 `learner_label_distribution.csv` 的时间/端口启发式与 audit 对照 |

## 配置

`configs/config.yaml` 中：

```yaml
visualization:
  metric_audit_min_samples: 50
  metric_audit_max_learners: 60
```

## 与 `scripts/` 的边界

- **本目录**：可视化与学习器定性产物的导出、补导出、demo 管线、定性效果分析入口。
- **`scripts/`**：数据准备、评估实验、sweep、GA 特征研究等；不再新增可视化 artifact 导出脚本。

`scripts/` 下保留同名**兼容转发**（打印 deprecation 后调用本目录），避免旧命令失效。
