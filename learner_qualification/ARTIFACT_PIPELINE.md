# 可视化产物流整理说明

本文记录 2026-05-22 对 Trident 脚本与可视化产物流做的整理。

这次整理的目标不是把所有研究脚本立刻迁移或重命名，而是先把
`run -> outputs/runs/<run_id> -> visualize` 这条正式链路收紧：

1. 一次 Trident run 完成后，自动写出可视化页面依赖的核心产物。
2. 旧 run 需要补产物时，提供一个统一导出入口。
3. 将可复用的可视化导出逻辑从零散 `scripts/` 中抽到
   `trident_stream/` 模块，避免脚本与实验主流程继续互相缠绕。
4. 给 `scripts/` 建立入口说明和用途分组，后续继续整理时有边界。

## 1. 整理前的问题

可视化页面读取 `outputs/runs/<run_id>/` 下的 CSV 与 JSON。Trident 主流程
本身已经生成了大部分页面数据，例如：

- learner 分布和时间序列
- dataset label 分布
- decision tree 产物
- dataset network topology
- learner network topology

但学习器拓扑指标审计仍主要依赖额外脚本补导出，相关入口分散在：

- `learner_qualification/export_dataset_network_topology.py`
- `learner_qualification/export_learner_network_topology.py`
- `learner_qualification/export_learner_topology_metric_audit.py`
- `learner_qualification/finish_viz_exports.sh`
- `learner_qualification/run_aligned_viz_pipeline.sh`

这会带来几个问题：

- run 跑完后页面数据不一定齐，使用者还要记住补跑脚本。
- 同类导出逻辑散在不同脚本里，脚本数量越多越难判断稳定入口。
- 导出脚本直接依赖实验对象重载数据，复用边界不清楚。
- 页面空态提示也会把用户引到多个细粒度脚本上。

## 2. 新的数据流

整理后，正式数据流如下：

```text
main.py
  -> TridentStreamingExperiment.run()
  -> outputs/runs/<run_id>/
       - run 基础产物
       - dataset_network_topology.json
       - learner_network_topology.json
       - learner_topology_metric_audit.json
  -> visualize/ 通过 run-data API 读取
```

其中可视化拓扑与指标导出由统一模块承接：

- `trident_stream/visualization_artifacts.py`

主流程把普通数据对象传给该模块：

- run 内的流数据 `data`
- canonical learner assignments
- `learner_label_distribution` 表
- 输出目录

该模块不负责跑 Trident 模型，也不负责控制前端；它只负责把可视化要用
的 artifact 落盘。这样它既能被主流程调用，也能被旧 run 的修复脚本调用。

## 3. 新增统一 artifact 模块

新增文件：

- `trident_stream/visualization_artifacts.py`

主要职责：

| 函数 | 作用 |
| --- | --- |
| `export_visualization_artifacts(...)` | 一次写出可视化拓扑与指标审计产物 |
| `save_learner_metric_audit(...)` | 保存学习器拓扑指标审计 JSON |
| `build_learner_metric_audit_payload(...)` | 从 DataFrame 构造审计 payload |
| `flows_for_metric_audit(...)` | 将 run 流表列名整理为指标审计口径 |

当前统一出口覆盖：

- `dataset_network_topology.json`
- `learner_network_topology.json`
- `learner_topology_metric_audit.json`

主流程仍在数据加载后尽早输出 dataset topology；run 结束阶段通过统一
artifact 模块输出 learner topology 与 learner metric audit。旧 run 补导出时
统一 exporter 会把三者都重建。

## 4. 一次 run 自动生成的页面产物

正常运行：

```bash
python3 main.py --config configs/config.yaml
```

run 目录中会包含前端读取的核心文件。除原有统计、决策树、分布表外，
这次整理保证下面的拓扑审计文件不再依赖手动补尾巴：

| 文件 | 页面用途 |
| --- | --- |
| `dataset_network_topology.json` | 数据集网络拓扑视图 |
| `learner_network_topology.json` | 学习器内部流拓扑视图 |
| `learner_topology_metric_audit.json` | 学习器拓扑指标与规则语义解释 |

前端继续通过 `visualize/vite.config.ts` 中的 run-data API 读取 run 目录，
没有引入新的前端数据源。

## 5. 旧 run 的补导出入口

新增脚本：

- `learner_qualification/export_visualization_artifacts.py`

用法：

```bash
python3 learner_qualification/export_visualization_artifacts.py outputs/runs/<run_id>
```

它会读取该 run 的：

- `config_snapshot.yaml`
- `sample_learner_assignments.csv`
- `learner_label_distribution.csv`

并按 run 配置重载流数据，然后重建三类可视化 artifact。

旧脚本仍保留，便于旧笔记和细粒度调试继续使用；但修复 run 页面产物时，
优先使用这个统一入口。

## 6. 配置项

在 `configs/config.yaml` 中增加：

```yaml
visualization:
  metric_audit_min_samples: 50
  metric_audit_max_learners: 60
```

含义：

| 配置 | 含义 |
| --- | --- |
| `visualization.metric_audit_min_samples` | 学习器至少有多少条 joined flow 才输出指标审计 |
| `visualization.metric_audit_max_learners` | 指标审计最多输出多少个学习器 |

若旧配置没有这段，代码使用同样的默认值。

## 7. 目录边界（2026-05-22 后续）

学习器定性 / 可视化 artifact 入口已迁至 **`learner_qualification/`**（见本目录 `README.md`）。
`scripts/` 保留研究脚本；同名文件为兼容转发。

`scripts/README.md` 中的用途族：

| 类别 | 示例 |
| --- | --- |
| 稳定入口 | `main.py`、`learner_qualification/export_visualization_artifacts.py` |
| 数据准备 | `prepare_*`、`align_*`、`collect_*`、`clean_*` |
| 产物导出与修复 | `export_*`、`rebuild_*`、`aggregate_*` |
| 离线分析 | `analyze_*`、`eda_*`、`explore_*`、`explain_*` |
| 评估实验 | `eval_*`、`run_*_source_test.py` |
| sweep 与配置 | `generate_*`、`run_hpo_*`、`summarize_*` |
| 特征搜索研究 | `ga_*`、`fit_*` |

后续新增稳定工作流时，应优先把可复用逻辑放进 `trident_stream/`，
而不是继续堆叠大型脚本。

## 8. 前端提示更新

这些前端空态提示已改为指向统一补导出入口：

- dataset topology 面板
- learner internal topology 面板
- learner metric audit 面板

统一提示命令：

```bash
python3 learner_qualification/export_visualization_artifacts.py outputs/runs/<run_id>
```

## 9. 验证结果

本轮整理后已验证：

```bash
python3 -m py_compile \
  trident_stream/visualization_artifacts.py \
  trident_stream/experiment.py \
  learner_qualification/export_visualization_artifacts.py

cd visualize
npm run lint
npm run build
```

并对现有 run 做了统一补导出烟测：

```bash
python3 scripts/export_visualization_artifacts.py \
  outputs/runs/20260521_190232_config_fpr1_x5_yeartagged_viz.yaml
```

该命令成功写出：

- `dataset_network_topology.json`
- `learner_network_topology.json`
- `learner_topology_metric_audit.json`

## 10. 与生产化的边界

这次整理提高了 run 与可视化之间的工程一致性，但不等于项目已经可以
直接接入真实生产环境。

当前更合适的定位是：

> 离线实验系统 + 真实流量旁路 PoC 的分析与可视化底座

若要进入生产环境，还需要继续补齐：

- 真实流量入口与 schema 校验
- 在线消费、背压、checkpoint 与崩溃恢复
- learner 状态持久化、模型版本和阈值版本管理
- 学习污染防护与新 learner 生命周期治理
- 结构化日志、监控、告警、权限和部署体系
- 多环境阈值校准与误报漏报验证

本轮工作的价值在于先把 artifact 输出边界立住，后续可以继续拆成：

```text
数据接入层
  -> Trident 检测与学习核心
  -> artifact / event 输出层
  -> 可视化与审计层
```

这样继续向真实流量 PoC 或生产架构演进时，不需要再从散乱脚本链路重新
清理一次。
