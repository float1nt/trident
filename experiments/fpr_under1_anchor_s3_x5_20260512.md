# FPR<1% 探索实验（anchor-s3, x5, 2026-05-12）

围绕 s3_threshold_decouple，扫描 benign_accept_scale / evt_risk / evt_quantile。

| 配置 | Run | learners | FPR | FNR | FPR<1% |
|---|---|---:|---:|---:|---|
| config_fpr1_b0p3_r0p0015_q0p97.yaml | 20260512_190034_config_fpr1_b0p3_r0p0015_q0p97.yaml | 43 | 0.018967 | 0.045125 | N |
| config_fpr1_b0p4_r0p0015_q0p95.yaml | 20260512_190309_config_fpr1_b0p4_r0p0015_q0p95.yaml | 43 | 0.020379 | 0.055192 | N |
| config_fpr1_b0p5_r0p0015_q0p95.yaml | 20260512_190635_config_fpr1_b0p5_r0p0015_q0p95.yaml | 36 | 0.020758 | 0.088853 | N |
| config_fpr1_b0p4_r0p002_q0p95.yaml | 20260512_190452_config_fpr1_b0p4_r0p002_q0p95.yaml | 37 | 0.023544 | 0.098177 | N |
| config_fpr1_b0p3_r0p002_q0p97.yaml | 20260512_190218_config_fpr1_b0p3_r0p002_q0p97.yaml | 44 | 0.027930 | 0.080929 | N |
| config_fpr1_b0p5_r0p002_q0p97.yaml | 20260512_190909_config_fpr1_b0p5_r0p002_q0p97.yaml | 45 | 0.031654 | 0.040748 | N |
| config_fpr1_b0p5_r0p002_q0p95.yaml | 20260512_190817_config_fpr1_b0p5_r0p002_q0p95.yaml | 40 | 0.031681 | 0.046597 | N |
| config_fpr1_b0p3_r0p0015_q0p95.yaml | 20260512_185943_config_fpr1_b0p3_r0p0015_q0p95.yaml | 38 | 0.032486 | 0.095501 | N |
| config_fpr1_b0p3_r0p002_q0p95.yaml | 20260512_190127_config_fpr1_b0p3_r0p002_q0p95.yaml | 36 | 0.038337 | 0.056279 | N |
| config_fpr1_b0p5_r0p0015_q0p97.yaml | 20260512_190725_config_fpr1_b0p5_r0p0015_q0p97.yaml | 43 | 0.045006 | 0.054936 | N |
| config_fpr1_b0p4_r0p002_q0p97.yaml | 20260512_190543_config_fpr1_b0p4_r0p002_q0p97.yaml | 43 | 0.048444 | 0.053659 | N |
| config_fpr1_b0p4_r0p0015_q0p97.yaml | 20260512_190401_config_fpr1_b0p4_r0p0015_q0p97.yaml | 38 | 0.051965 | 0.036076 | N |

- 命中 FPR<1%：**0 / 12**
- 未命中；最接近配置：`config_fpr1_b0p3_r0p0015_q0p97.yaml`（FPR=0.018967, FNR=0.045125, learners=43）。
