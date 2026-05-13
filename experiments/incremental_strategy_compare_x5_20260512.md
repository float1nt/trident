# 增量训练策略对比实验（x5, 2026-05-12）

固定 `dbscan_eps=1.3, min_samples=10`，对不同增量重训防污染策略做对比。

| 策略 | Run | learners | FPR | FNR | increment批次attack_ratio均值 | NEW_1 attack_ratio | NEW_7 attack_ratio | NEW_1首次污染窗口 | NEW_7首次污染窗口 |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| s0_baseline | 20260512_175453_config_increment_s0_baseline.yaml | 28 | 0.017113 | 0.162944 | 0.515534 | 0.319975 | 0.543791 | 375900-385900 | 1175900-1185900 |
| s1_history_anchor | 20260512_175548_config_increment_s1_history_anchor.yaml | 13 | 0.020503 | 0.260807 | 0.596771 | 0.000000 | 0.977742 | - | 755900-765900 |
| s2_quality_gate | 20260512_175644_config_increment_s2_quality_gate.yaml | 26 | 0.017183 | 0.162944 | 0.524620 | 0.319977 | 0.540908 | 375900-385900 | 1175900-1185900 |
| s3_threshold_decouple | 20260512_175741_config_increment_s3_threshold_decouple.yaml | 42 | 0.023254 | 0.068124 | 0.454343 | 0.079192 | 0.000000 | 375900-385900 | - |
| s4_newlearner_cooldown | 20260512_175839_config_increment_s4_newlearner_cooldown.yaml | 27 | 0.024598 | 0.082532 | 0.539386 | 0.289754 | 0.953134 | 375900-385900 | - |
| s5_stratified_sampling | 20260512_175935_config_increment_s5_stratified_sampling.yaml | 80 | 0.026843 | 0.100403 | 0.464462 | 0.006325 | 0.000000 | - | - |
| s6_combo | 20260512_180040_config_increment_s6_combo.yaml | 11 | 0.009997 | 0.345943 | 0.547641 | 0.000000 | 0.000000 | - | - |

## 观察
- NEW_1污染最低：`s1_history_anchor`（attack_ratio=0.000000）。
- NEW_7污染最低：`s3_threshold_decouple`（attack_ratio=0.000000）。
- 增量批次平均污染最低：`s3_threshold_decouple`（increment attack_ratio均值=0.454343）。
- 请结合 FPR/FNR 一起选策略，避免只追求“低污染”导致漏报上升。
