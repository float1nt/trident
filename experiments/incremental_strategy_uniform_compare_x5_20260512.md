# 增量训练策略对比实验（x5, uniform learner treatment, 2026-05-12）

全部 learner 一视同仁（不做 BENIGN 特殊门槛/优先级），对不同增量重训策略做对比。


| 策略                     | Run                                                                  | learners | FPR      | FNR      | increment批次attack_ratio均值 | NEW_1 attack_ratio | NEW_7 attack_ratio | NEW_1首次污染窗口   | NEW_7首次污染窗口   |
| ---------------------- | -------------------------------------------------------------------- | -------- | -------- | -------- | ------------------------- | ------------------ | ------------------ | ------------- | ------------- |
| u0_baseline_uniform    | 20260512_181316_config_increment_uniform_u0_baseline_uniform.yaml    | 28       | 0.013747 | 0.273648 | 0.541206                  | 0.000000           | 0.985073           | -             | 745900-755900 |
| u1_history_anchor      | 20260512_181406_config_increment_uniform_u1_history_anchor.yaml      | 16       | 0.003057 | 0.515493 | 0.584531                  | 0.000000           | 0.997611           | -             | 805900-815900 |
| u2_quality_gate        | 20260512_181453_config_increment_uniform_u2_quality_gate.yaml        | 29       | 0.015180 | 0.273648 | 0.551322                  | 0.000000           | 0.985073           | -             | 745900-755900 |
| u3_threshold_decouple  | 20260512_181543_config_increment_uniform_u3_threshold_decouple.yaml  | 40       | 0.038762 | 0.231109 | 0.580765                  | 0.439133           | 0.000000           | 455900-465900 | -             |
| u4_cooldown            | 20260512_181633_config_increment_uniform_u4_cooldown.yaml            | 24       | 0.015896 | 0.274156 | 0.545765                  | 0.000000           | 0.975775           | -             | 765900-775900 |
| u5_stratified_sampling | 20260512_181721_config_increment_uniform_u5_stratified_sampling.yaml | 84       | 0.026584 | 0.031574 | 0.444332                  | 0.037758           | 0.036500           | 575900-585900 | -             |
| u6_combo_balanced      | 20260512_181821_config_increment_uniform_u6_combo_balanced.yaml      | 16       | 0.005072 | 0.466191 | 0.593656                  | 0.000000           | 1.000000           | -             | 825900-835900 |
| u7_combo_aggressive    | 20260512_181910_config_increment_uniform_u7_combo_aggressive.yaml    | 13       | 0.003191 | 0.633244 | 0.568067                  | 0.000000           | 0.997191           | -             | -             |


## 观察

- NEW_1污染最低：`u0_baseline_uniform`（attack_ratio=0.000000）。
- NEW_7污染最低：`u3_threshold_decouple`（attack_ratio=0.000000）。
- 增量批次平均污染最低：`u5_stratified_sampling`（0.444332）。
- 最低漏报（FNR）：`u5_stratified_sampling`（FNR=0.031574, FPR=0.026584）。
- 选型建议请同时考虑污染、FPR/FNR 与 learner 数量。

