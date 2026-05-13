# 目标约束调参实验（uniform + u5 base, 2026-05-12）

目标：learners 20~30，FPR<1%，FNR<10%。

| 配置 | Run | ncls | eps | evt_risk | learners | FPR | FNR | 命中目标 | 距离 |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|
| config_goal_u5_ncls1000_eps1p3_risk0p0015.yaml | 20260512_184716_config_goal_u5_ncls1000_eps1p3_risk0p0015.yaml | 1000 | 1.30 | 0.0015 | 66 | 0.022321 | 0.111470 | N | 4.947 |
| config_goal_u5_ncls800_eps1p3_risk0p0015.yaml | 20260512_185114_config_goal_u5_ncls800_eps1p3_risk0p0015.yaml | 800 | 1.30 | 0.0015 | 76 | 0.023016 | 0.031422 | N | 5.902 |
| config_goal_u5_ncls800_eps1p35_risk0p0015.yaml | 20260512_184915_config_goal_u5_ncls800_eps1p35_risk0p0015.yaml | 800 | 1.35 | 0.0015 | 72 | 0.027474 | 0.064455 | N | 5.947 |
| config_goal_u5_ncls800_eps1p3_risk0p002.yaml | 20260512_185215_config_goal_u5_ncls800_eps1p3_risk0p002.yaml | 800 | 1.30 | 0.0020 | 75 | 0.025207 | 0.022340 | N | 6.021 |
| config_goal_u5_ncls800_eps1p35_risk0p002.yaml | 20260512_185013_config_goal_u5_ncls800_eps1p35_risk0p002.yaml | 800 | 1.35 | 0.0020 | 79 | 0.025371 | 0.046209 | N | 6.437 |
| config_goal_u5_ncls1000_eps1p35_risk0p002.yaml | 20260512_184614_config_goal_u5_ncls1000_eps1p35_risk0p002.yaml | 1000 | 1.35 | 0.0020 | 80 | 0.024733 | 0.045512 | N | 6.473 |
| config_goal_u5_ncls1000_eps1p3_risk0p002.yaml | 20260512_184814_config_goal_u5_ncls1000_eps1p3_risk0p002.yaml | 1000 | 1.30 | 0.0020 | 73 | 0.034812 | 0.037664 | N | 6.781 |
| config_goal_u5_ncls1000_eps1p35_risk0p0015.yaml | 20260512_184514_config_goal_u5_ncls1000_eps1p35_risk0p0015.yaml | 1000 | 1.35 | 0.0015 | 70 | 0.046473 | 0.036523 | N | 7.647 |

- 命中目标配置数：**0** / 8
- 最优近邻配置：`config_goal_u5_ncls1000_eps1p3_risk0p0015.yaml`（learners=66, FPR=0.022321, FNR=0.111470）。
