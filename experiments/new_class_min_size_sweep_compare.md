# `new_class_min_size` 四组对比实验记录

本实验在同一主流程参数下，仅改变 `tmagnifier.new_class_min_size`，比较其对 learner 规模与风险指标的影响。

## 1. 实验配置

- 配置目录：`configs/experiments/new_class_min_size_sweep/`
- 对照配置：
  - `config_compact_newclass_300.yaml`
  - `config_compact_newclass_500.yaml`
  - `config_compact_newclass_1000.yaml`
  - `config_compact_newclass_2000.yaml`
- 其余关键参数保持一致：
  - `runtime.feature_profile=compact_stats_no_env`
  - `stream.window_size=10000`
  - `tmagnifier.dbscan_eps=1.2`
  - `tmagnifier.dbscan_min_samples=15`

## 2. 结果汇总


| `new_class_min_size` | Run 名称（时间戳_配置文件名）                                 | 特征维度 | 最终 learner 数 | 误报率(FPR) | 漏报率(FNR) |
| -------------------- | ------------------------------------------------- | ---- | ------------ | -------- | -------- |
| 300                  | 20260512_150824_config_compact_newclass_300.yaml  | 26   | 25           | 0.054416 | 0.369125 |
| 500                  | 20260512_145410_config_compact_newclass_500.yaml  | 26   | 23           | 0.023560 | 0.304372 |
| 1000                 | 20260512_145424_config_compact_newclass_1000.yaml | 26   | 18           | 0.028468 | 0.371399 |
| 2000                 | 20260512_145437_config_compact_newclass_2000.yaml | 26   | 12           | 0.038638 | 0.443676 |


指标来源：

- `outputs/runs/<run_id>/run_summary.txt`：`feature_dim`、`final_learner_count`
- `outputs/runs/<run_id>/metrics.json`：`risk_false_positive_rate`、`risk_false_negative_rate`

## 3. 对聚合与纯度的影响（新增）

聚合统计来源：

- `outputs/runs/<run_id>/learner_aggregation_summary.json`
- `outputs/runs/<run_id>/learner_aggregated_distribution.csv`


| `new_class_min_size` | 聚合前 learner | 聚合后 aggregate | 压缩率   | 多成员组件数 | 最大组件规模 |
| -------------------- | ----------- | ------------- | ----- | ------ | ------ |
| 300                  | 26          | 15            | 42.3% | 3      | 8      |
| 500                  | 24          | 18            | 25.0% | 4      | 4      |
| 1000                 | 19          | 10            | 47.4% | 3      | 6      |
| 2000                 | 13          | 8             | 38.5% | 1      | 6      |



| `new_class_min_size` | aggregate 主导标签纯度均值（dominant_ratio） | 最低纯度组件 |
| -------------------- | ---------------------------------- | ------ |
| 300                  | 0.719                              | 0.162  |
| 500                  | 0.737                              | 0.138  |
| 1000                 | 0.628                              | 0.180  |
| 2000                 | 0.691                              | 0.221  |


补充（只看多成员组件）：

- 300：多成员组件平均纯度约 `0.350`（3 个多成员组件）
- 500：多成员组件平均纯度约 `0.347`（4 个多成员组件）
- 1000：多成员组件平均纯度约 `0.304`（3 个多成员组件）
- 2000：多成员组件纯度约 `0.267`（1 个多成员组件）

解释：

- `1000` 在这组里聚合压缩最强（`47.4%`），说明更容易把不同 learner 合并。
- `300` 的聚合也很强（`42.3%`），并出现最大规模 `8` 的聚合组件，说明在更低阈值下会形成更大的合并簇。
- 但压缩增强并不等价于更“干净”的聚合：`1000` 的整体纯度均值最低，提示混合标签更明显。
- `2000` 的组件数最少，但主要由一个大组件驱动（规模 6，纯度约 `0.267`），存在较强混合风险。

## 4. 结论

- 随 `new_class_min_size` 增大，最终 learner 数明显下降：`25 -> 23 -> 18 -> 12`。
- 该组里风险指标并非“阈值越小越好”：`300` 的 FPR 明显上升（`0.054416`），`500` 反而是 FPR/FNR 的最优点。
- 仅看聚合压缩效率，`new_class_min_size=1000` 最强；若综合风险指标与聚合纯度，`new_class_min_size=500` 仍是更稳妥的折中选择。

