# DBSCAN 超参数敏感性实验（x5, AE, 2026-05-12）

基于 `20260512_155215_config_classifier_compare_x5_ae.yaml` 作为基线，仅扫描 `tmagnifier.dbscan_eps` 与 `tmagnifier.dbscan_min_samples`。

| 配置 | Run | dbscan_eps | dbscan_min_samples | final learners | FPR | FNR | 低纯度learner(<0.5) |
|---|---|---:|---:|---:|---:|---:|---:|
| config_dbscan_eps1p2_min10.yaml | 20260512_161541_config_dbscan_eps1p2_min10.yaml | 1.2 | 10 | 30 | 0.005393 | 0.519874 | 6 |
| config_dbscan_eps1p0_min15.yaml | 20260512_161221_config_dbscan_eps1p0_min15.yaml | 1.0 | 15 | 36 | 0.014677 | 0.354119 | 10 |
| config_dbscan_eps1p3_min10.yaml | 20260512_161738_config_dbscan_eps1p3_min10.yaml | 1.3 | 10 | 28 | 0.017113 | 0.162944 | 8 |
| config_dbscan_eps1p1_min15.yaml | 20260512_161422_config_dbscan_eps1p1_min15.yaml | 1.1 | 15 | 35 | 0.017283 | 0.369743 | 8 |
| config_dbscan_eps1p3_min15.yaml | 20260512_161819_config_dbscan_eps1p3_min15.yaml | 1.3 | 15 | 31 | 0.022578 | 0.154459 | 8 |
| config_dbscan_eps1p0_min20.yaml | 20260512_161302_config_dbscan_eps1p0_min20.yaml | 1.0 | 20 | 43 | 0.023344 | 0.308054 | 13 |
| config_dbscan_eps1p2_min20.yaml | 20260512_161657_config_dbscan_eps1p2_min20.yaml | 1.2 | 20 | 37 | 0.023613 | 0.167412 | 7 |
| config_dbscan_eps1p1_min20.yaml | 20260512_161502_config_dbscan_eps1p1_min20.yaml | 1.1 | 20 | 29 | 0.041464 | 0.242104 | 8 |
| config_dbscan_eps1p2_min15.yaml | 20260512_161619_config_dbscan_eps1p2_min15.yaml | 1.2 | 15 | 28 | 0.042718 | 0.261727 | 4 |
| config_dbscan_eps1p3_min20.yaml | 20260512_161858_config_dbscan_eps1p3_min20.yaml | 1.3 | 20 | 24 | 0.044159 | 0.224391 | 5 |
| config_dbscan_eps1p1_min10.yaml | 20260512_161344_config_dbscan_eps1p1_min10.yaml | 1.1 | 10 | 31 | 0.061946 | 0.189414 | 7 |
| config_dbscan_eps1p0_min10.yaml | 20260512_161135_config_dbscan_eps1p0_min10.yaml | 1.0 | 10 | 44 | 0.079471 | 0.100636 | 7 |

## 结论
- 最低 FPR：`eps=1.2, min_samples=10`（Run `20260512_161541_config_dbscan_eps1p2_min10.yaml`，FPR=0.005393）。
- 最低 FNR：`eps=1.0, min_samples=10`（Run `20260512_161135_config_dbscan_eps1p0_min10.yaml`，FNR=0.100636）。
- 折中参考：`eps=1.3, min_samples=15`（Run `20260512_161819_config_dbscan_eps1p3_min15.yaml`，FPR=0.022578, FNR=0.154459）。
