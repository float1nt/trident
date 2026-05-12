# tscissors 超参数敏感性实验记录（2026-05-12）

## 1. 实验背景与目标

基于 `outputs/runs/20260512_145410/config_snapshot.yaml` 的基线配置，针对 `tscissors` 三个超参数做敏感性实验：

- `evt_quantile`
- `evt_risk`
- `fallback_quantile`

目标是缓解 `learner_label_distribution.csv` 中 learner 混杂（主导标签纯度偏低）问题，同时观察风险指标变化。

## 2. 实验设置

- 配置目录：`configs/experiments/tscissors_sensitivity`
- 扫描配置数：9 组
- 其余参数固定（数据集、`stream`、`tsieve`、`tmagnifier` 与基线一致）

评估口径：

- 风险：`FPR` / `FNR`（来自 `metrics.json`）
- 混杂度：`dominant_ratio < 0.5` 与 `< 0.3` 的 learner 数
- `UNKNOWN` 纯度：`UNKNOWN` learner 的 `dominant_ratio`

## 3. 对比结果

| 配置文件 | Run | evt_quantile | evt_risk | fallback_quantile | final learners | FPR | FNR | 低纯度<0.5 | 极低纯度<0.3 | UNKNOWN纯度 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| config_tscissors_risk2e3.yaml | 20260512_151930_config_tscissors_risk2e3.yaml | 0.950 | 0.0020 | 0.990 | 22 | 0.002501 | 0.624943 | 8 | 2 | 0.307 |
| config_tscissors_q97.yaml | 20260512_151918_config_tscissors_q97.yaml | 0.970 | 0.0010 | 0.990 | 20 | 0.003233 | 0.552861 | 10 | 2 | 0.316 |
| config_tscissors_loose_combo.yaml | 20260512_151851_config_tscissors_loose_combo.yaml | 0.930 | 0.0020 | 0.980 | 17 | 0.005952 | 0.491069 | 8 | 3 | 0.256 |
| config_tscissors_fb98.yaml | 20260512_151825_config_tscissors_fb98.yaml | 0.950 | 0.0010 | 0.980 | 16 | 0.008613 | 0.581460 | 6 | 4 | 0.421 |
| config_tscissors_q93.yaml | 20260512_151905_config_tscissors_q93.yaml | 0.930 | 0.0010 | 0.990 | 18 | 0.011984 | 0.811536 | 8 | 1 | 0.434 |
| config_tscissors_strict_combo.yaml | 20260512_151955_config_tscissors_strict_combo.yaml | 0.970 | 0.0005 | 0.995 | 21 | 0.012510 | 0.474439 | 7 | 2 | 0.390 |
| config_tscissors_baseline.yaml | 20260512_151812_config_tscissors_baseline.yaml | 0.950 | 0.0010 | 0.990 | 23 | 0.023560 | 0.304372 | 7 | 2 | 0.393 |
| config_tscissors_fb995.yaml | 20260512_151838_config_tscissors_fb995.yaml | 0.950 | 0.0010 | 0.995 | 17 | 0.028232 | 0.436757 | 8 | 2 | 0.309 |
| config_tscissors_risk5e4.yaml | 20260512_151943_config_tscissors_risk5e4.yaml | 0.950 | 0.0005 | 0.990 | 15 | 0.034185 | 0.646932 | 8 | 3 | 0.309 |

## 4. 结果解读

- 追求最低误报时，`evt_risk=0.002`（`config_tscissors_risk2e3.yaml`）最优，但 FNR 大幅变差。
- 追求最低漏报时，当前基线（`config_tscissors_baseline.yaml`）仍然最好。
- 以“低纯度 learner 数”衡量混杂，`config_tscissors_fb98.yaml` 最优（`<0.5` 仅 6 个），但 FNR 不理想。
- 说明 `tscissors` 参数主要影响“误报-漏报-混杂”的权衡，而不是单向改善。

## 5. 建议参数

- 若目标是**先压混杂**：优先 `config_tscissors_fb98.yaml`（`0.95 / 0.001 / 0.98`）。
- 若目标是**先压误报**：优先 `config_tscissors_risk2e3.yaml`（`evt_risk=0.002`）。
- 若目标是**先保漏报**：保留基线 `config_tscissors_baseline.yaml`。

后续建议：围绕 `fallback_quantile=0.98` 做二阶段小范围微调（仅扫 `evt_risk`），寻找“混杂下降 + FNR 可接受”的折中点。
