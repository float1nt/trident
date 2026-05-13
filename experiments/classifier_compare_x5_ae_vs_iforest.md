# x5 数据集分类器对比实验（AE vs IsolationForest）

## 1. 实验目标

在相同流式框架与超参数下，仅替换 `tsieve` 分类器后端，比较：

- 风险误报率（`risk_false_positive_rate`）
- 风险漏报率（`risk_false_negative_rate`）
- 最终 learner 数量（`final_learner_count`）

## 2. 对照设置

- 数据集：`data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv`
- 固定参数：
  - `runtime.feature_profile=compact_stats_no_env`
  - `tscissors`: `evt_quantile=0.95`, `evt_risk=0.001`, `fallback_quantile=0.99`
  - `tmagnifier`: `dbscan_eps=1.2`, `dbscan_min_samples=15`, `new_class_min_size=500`
- 唯一变化：`tsieve.classifier_backend`

对应配置：

- `configs/experiments/classifier_compare_x5/config_classifier_compare_x5_ae.yaml`
- `configs/experiments/classifier_compare_x5/config_classifier_compare_x5_iforest.yaml`

## 3. 结果对比

| 分类器 | Run 名称（时间戳_配置文件） | final learners | FPR | FNR |
|---|---|---:|---:|---:|
| AE | 20260512_155215_config_classifier_compare_x5_ae.yaml | 28 | 0.042718 | 0.261727 |
| IsolationForest | 20260512_155253_config_classifier_compare_x5_iforest.yaml | 6 | 0.235264 | 0.175045 |

## 4. 结果解读

- IsolationForest 显著降低了漏报（`FNR` 下降），但误报大幅升高（`FPR` 明显变差）。
- IF 的 learner 数量显著更少（`28 -> 6`），说明模型边界更粗、聚合更强，导致更多样本被统一归入攻击侧。
- AE 在当前设定下更均衡：误报更低，但漏报更高。

## 5. 结论与建议

- 若优先目标是**控制误报**，当前对比下应优先 AE。
- 若优先目标是**压低漏报**，IF 有优势，但需要进一步调参与后处理降低误报。
- 建议下一步只对 IF 做小范围调参（如 `iforest_n_estimators`、`benign_accept_scale`、`evt_quantile`）以寻找可接受折中点。
