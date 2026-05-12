# 非 x5 特征工程对照实验（完整记录）

本实验在同一主流程参数下，仅切换 `feature_profile`，评估“特征维度变化”对 learner 规模与风险指标的影响。

## 1. 实验目标

对比三种特征配置对以下结果的影响：

- 最终 learner 数量（`final_learner_count`）
- 风险误报率（`risk_false_positive_rate`）
- 风险漏报率（`risk_false_negative_rate`）

## 2. 固定条件（控制变量）

- 数据集：`data/aligned_2017_2019_2026_sampled_yeartagged_for_main.csv`（非 x5）
- 初始化与窗口：
  - `stream.init_ratio=0.01`
  - `stream.init_known_mode=benign_only`
  - `stream.window_size=10000`
- 新类发现：
  - `tmagnifier.dbscan_eps=1.2`
  - `tmagnifier.dbscan_min_samples=15`
  - `tmagnifier.new_class_min_size=2000`
- 评估口径：
  - 使用当前主流程新公式（按 `dominant_label` 判定簇属于良性系/攻击系）
- 其余参数保持一致，仅切换 `runtime.feature_profile`。

## 2.1 特征工程变体说明

三种对照配置仅在 `runtime.feature_profile` 上不同，对应含义如下：

- `all_numeric_no_env`
  - 去除环境字段后，保留全部数值特征（信息最完整、维度最高）。

- `stable_stats_no_env`
  - 去除环境字段后，保留预定义的稳定统计特征子集（Flow/IAT/Packet/Flag/Active/Idle 等）。

- `compact_stats_no_env`
  - 在稳定统计子集上进一步压缩，仅保留核心统计特征（更低维、更紧凑）。

统一剔除的环境字段包括：`Src IP`、`Dst IP`、`Src Port`、`Dst Port`、`Protocol`、`Timestamp`、`Label` 等。  
对应实现定义位于：`trident_stream/experiment.py` 中的 `ENVIRONMENT_COLUMNS`、`STABLE_STATS_FEATURES`、`COMPACT_STATS_FEATURES`。

## 3. 实验过程（详细）

### 3.1 配置准备

基于同一基准配置生成三份对照配置：

- `configs/experiments/nonx5_feature_compare/config_nonx5_compact.yaml`
  - `feature_profile: compact_stats_no_env`
- `configs/experiments/nonx5_feature_compare/config_nonx5_stable.yaml`
  - `feature_profile: stable_stats_no_env`
- `configs/experiments/nonx5_feature_compare/config_nonx5_all_numeric.yaml`
  - `feature_profile: all_numeric_no_env`

### 3.2 运行顺序

按以下顺序独立运行，每次由 `main.py` 自动生成新 `run_id`：

```bash
python3 main.py --config configs/experiments/nonx5_feature_compare/config_nonx5_compact.yaml
python3 main.py --config configs/experiments/nonx5_feature_compare/config_nonx5_stable.yaml
python3 main.py --config configs/experiments/nonx5_feature_compare/config_nonx5_all_numeric.yaml
```

### 3.3 结果提取

每个 run 从以下文件提取指标：

- `run_summary.txt`：`feature_dim`、`final_learner_count`
- `metrics.json`：`risk_false_positive_rate`、`risk_false_negative_rate`

## 4. 对照结果

| 特征配置 | Run 名称（时间戳_配置文件名） | 特征维度 | 最终 learner 数 | 误报率(FPR) | 漏报率(FNR) |
|---|---|---:|---:|---:|---:|
| compact_stats_no_env | 20260512_144324_config_nonx5_compact.yaml | 26 | 12 | 0.038638 | 0.443676 |
| stable_stats_no_env | 20260512_144340_config_nonx5_stable.yaml | 65 | 24 | 0.016026 | 0.577250 |
| all_numeric_no_env | 20260512_144409_config_nonx5_all_numeric.yaml | 76 | 20 | 0.007591 | 0.472711 |

## 5. 变动分析（核心）

### 5.1 learner 数量变化

- `compact -> stable`：`12 -> 24`（+100%）
- `compact -> all_numeric`：`12 -> 20`（+66.7%）
- `stable -> all_numeric`：`24 -> 20`（-16.7%）

结论：提升特征维度后，整体上 learner 会增加（表征更细粒度，新增簇更容易被拆分出来）；但 `stable(65维)` 比 `all_numeric(76维)` learner 更多，说明维度并非唯一因素，特征集合的“结构偏好”也会影响聚类与接收边界。

### 5.2 误报变化（FPR）

- `compact -> stable`：0.038638 -> 0.016026（下降 58.5%）
- `compact -> all_numeric`：0.038638 -> 0.007591（下降 80.4%）
- `stable -> all_numeric`：0.016026 -> 0.007591（下降 52.6%）

结论：特征更丰富时，良性样本被划入攻击系簇的概率明显下降，误报持续改善；`all_numeric_no_env` 在本组中误报最低。

### 5.3 漏报变化（FNR）

- `compact -> stable`：0.443676 -> 0.577250（上升 30.1%）
- `compact -> all_numeric`：0.443676 -> 0.472711（上升 6.5%）
- `stable -> all_numeric`：0.577250 -> 0.472711（下降 18.1%）

结论：`stable` 配置在本组中出现最高漏报，说明其簇主导关系下“攻击混入良性系簇 + UNKNOWN攻击”规模更大；`compact` 漏报最低，`all_numeric` 介于两者之间。

### 5.4 对聚合效果的影响（新增）

为回答“不同特征配置是否影响 learner 聚合”，补充对 `learner_aggregation_summary.json` 与 `learner_aggregation_mapping.csv` 的对照：

| 特征配置 | 聚合前 learner_count | 聚合后 aggregate_count | 减少数量 | 压缩率 |
|---|---:|---:|---:|---:|
| compact_stats_no_env | 13 | 8 | 5 | 38.5% |
| stable_stats_no_env | 25 | 24 | 1 | 4.0% |
| all_numeric_no_env | 21 | 19 | 2 | 9.5% |

补充观察：

- `compact` 只有 8 个聚合组件，但其中存在一个 `component_size=6` 的大组件（6 个 learner 被合并到同一 aggregate），其余为单点组件。
- `stable` 基本不发生聚合（仅一个 `component_size=2`），大多数 learner 仍是单独组件。
- `all_numeric` 介于两者之间（一个 `component_size=3`，其余多数单点）。

结论（聚合视角）：

- 你的判断是对的：在本组实验中，`compact_stats_no_env` 明显更容易聚合不同 learner。
- 但这是一把双刃剑：`compact` 的强聚合提升了组件压缩效率，也可能把语义差异较大的 learner 合到一起（存在“过聚合”风险）；因此需要结合误报/漏报与组件纯度一起看，而不能只看 aggregate 数量。

## 6. 最终结论与建议

- learner 数最多：`stable_stats_no_env`（Run `20260512_144340_config_nonx5_stable.yaml`，24 个）
- 误报最低：`all_numeric_no_env`（Run `20260512_144409_config_nonx5_all_numeric.yaml`，FPR=0.007591）
- 漏报最低：`compact_stats_no_env`（Run `20260512_144324_config_nonx5_compact.yaml`，FNR=0.443676）

建议：

- 若目标是**压低误报**：优先 `all_numeric_no_env`
- 若目标是**控制 learner 规模 + 保持较低漏报**：优先 `compact_stats_no_env`
- 若目标是**中间折中**：可从 `all_numeric_no_env` 起步，再通过 `dbscan_eps` 与 `new_class_min_size` 做小步网格微调。
- 若目标是**提升聚合压缩效率**：`compact_stats_no_env` 更有优势，但建议额外监控“聚合组件纯度”（每个 aggregate 的主导标签占比）以防过聚合。

