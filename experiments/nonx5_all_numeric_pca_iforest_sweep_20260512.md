# nonx5 all_numeric + PCA + IsolationForest 对比实验（2026-05-12）

在 `all_numeric_no_env` 特征配置下，固定其余参数，使用 `tsieve.classifier_backend=iforest`，对 `runtime.pca_n_components` 做对比：15 / 20 / 25 / 30。

| PCA维度 | 配置 | Run | 实际特征维度 | final learners | FPR | FNR |
|---:|---|---|---:|---:|---:|---:|
| 15 | config_nonx5_all_numeric_pca15_iforest.yaml | 20260512_164400_config_nonx5_all_numeric_pca15_iforest.yaml | 15 | 2 | 0.000000 | 1.000000 |
| 20 | config_nonx5_all_numeric_pca20_iforest.yaml | 20260512_164436_config_nonx5_all_numeric_pca20_iforest.yaml | 20 | 3 | 0.000000 | 1.000000 |
| 25 | config_nonx5_all_numeric_pca25_iforest.yaml | 20260512_164514_config_nonx5_all_numeric_pca25_iforest.yaml | 25 | 3 | 0.000000 | 1.000000 |
| 30 | config_nonx5_all_numeric_pca30_iforest.yaml | 20260512_164552_config_nonx5_all_numeric_pca30_iforest.yaml | 30 | 3 | 0.000000 | 1.000000 |

## 结论
- 最低 FPR：PCA=15（Run `20260512_164400_config_nonx5_all_numeric_pca15_iforest.yaml`，FPR=0.000000）。
- 最低 FNR：PCA=15（Run `20260512_164400_config_nonx5_all_numeric_pca15_iforest.yaml`，FNR=1.000000）。
- 折中参考：PCA=15（Run `20260512_164400_config_nonx5_all_numeric_pca15_iforest.yaml`，FPR=0.000000, FNR=1.000000）。
