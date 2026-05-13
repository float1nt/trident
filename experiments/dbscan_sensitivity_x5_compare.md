# DBSCAN 参数对比实验结果（x5, AE）

## 1. 实验目的

在固定 `tsieve=AE` 与其余参数不变的前提下，对 `tmagnifier` 的两个关键参数进行网格对比：

- `dbscan_eps ∈ {1.0, 1.1, 1.2, 1.3}`
- `dbscan_min_samples ∈ {10, 15, 20}`

目标是观察对以下指标的影响：

- 风险误报率（FPR）
- 风险漏报率（FNR）
- learner 数量（`final_learner_count`）

## 2. 固定条件

- 基线配置来源：`config_classifier_compare_x5_ae.yaml`
- 数据集：`aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv`
- 其余核心参数保持不变（`tscissors`、`tsieve`、`stream`、`feature_profile` 等）。

## 3. 对比结果（12 组）

| 参数组合 (`eps`, `min_samples`) | Run | learners | FPR | FNR |
|---|---|---:|---:|---:|
| (1.2, 10) | `20260512_161541_config_dbscan_eps1p2_min10.yaml` | 30 | 0.005393 | 0.519874 |
| (1.0, 15) | `20260512_161221_config_dbscan_eps1p0_min15.yaml` | 36 | 0.014677 | 0.354119 |
| (1.3, 10) | `20260512_161738_config_dbscan_eps1p3_min10.yaml` | 28 | 0.017113 | 0.162944 |
| (1.1, 15) | `20260512_161422_config_dbscan_eps1p1_min15.yaml` | 35 | 0.017283 | 0.369743 |
| (1.3, 15) | `20260512_161819_config_dbscan_eps1p3_min15.yaml` | 31 | 0.022578 | 0.154459 |
| (1.0, 20) | `20260512_161302_config_dbscan_eps1p0_min20.yaml` | 43 | 0.023344 | 0.308054 |
| (1.2, 20) | `20260512_161657_config_dbscan_eps1p2_min20.yaml` | 37 | 0.023613 | 0.167412 |
| (1.1, 20) | `20260512_161502_config_dbscan_eps1p1_min20.yaml` | 29 | 0.041464 | 0.242104 |
| (1.2, 15) | `20260512_161619_config_dbscan_eps1p2_min15.yaml` | 28 | 0.042718 | 0.261727 |
| (1.3, 20) | `20260512_161858_config_dbscan_eps1p3_min20.yaml` | 24 | 0.044159 | 0.224391 |
| (1.1, 10) | `20260512_161344_config_dbscan_eps1p1_min10.yaml` | 31 | 0.061946 | 0.189414 |
| (1.0, 10) | `20260512_161135_config_dbscan_eps1p0_min10.yaml` | 44 | 0.079471 | 0.100636 |

## 4. 结论

- **最低 FPR**：`(1.2, 10)`，但 FNR 明显偏高（更容易漏报）。
- **最低 FNR**：`(1.0, 10)`，但 FPR 明显偏高（误报较重）。
- **更均衡折中**：`(1.3, 15)`，在 FPR/FNR 间取得更平衡表现。

## 5. 建议

- 若业务优先“少误报”：考虑 `(1.2, 10)`，并配合后续补漏策略。
- 若业务优先“少漏报”：考虑 `(1.0, 10)`，并配合误报抑制策略。
- 若需要综合可用性：优先试 `(1.3, 15)` 作为下一阶段主配置。
