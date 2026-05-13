# nonx5 all_numeric PCA 降维对比实验（2026-05-12）

在 `all_numeric_no_env` 特征配置下，固定其他参数，仅对 `runtime.pca_n_components` 做对比：15 / 20 / 25 / 30。

| PCA维度 | 配置 | Run | 实际特征维度 | final learners | FPR | FNR |
|---:|---|---|---:|---:|---:|---:|
| 15 | config_nonx5_all_numeric_pca15.yaml | 20260512_164053_config_nonx5_all_numeric_pca15.yaml | 15 | 9 | 0.016221 | 0.941790 |
| 20 | config_nonx5_all_numeric_pca20.yaml | 20260512_164108_config_nonx5_all_numeric_pca20.yaml | 20 | 10 | 0.010085 | 0.650046 |
| 25 | config_nonx5_all_numeric_pca25.yaml | 20260512_164122_config_nonx5_all_numeric_pca25.yaml | 25 | 9 | 0.014118 | 0.831569 |
| 30 | config_nonx5_all_numeric_pca30.yaml | 20260512_164136_config_nonx5_all_numeric_pca30.yaml | 30 | 8 | 0.001092 | 0.973539 |

## 结论
- 最低 FPR：PCA=30（Run `20260512_164136_config_nonx5_all_numeric_pca30.yaml`，FPR=0.001092）。
- 最低 FNR：PCA=20（Run `20260512_164108_config_nonx5_all_numeric_pca20.yaml`，FNR=0.650046）。
- 折中参考：PCA=20（Run `20260512_164108_config_nonx5_all_numeric_pca20.yaml`，FPR=0.010085, FNR=0.650046）。
