# Trident 性能测试说明：实测结果与不考虑磁盘 IO 的理论上界（通俗版）

本文说明：benchmark 脚本**量的是什么**、**结果文件在哪儿**、**为什么有两个速度**、以及在**不写磁盘读取**的理想假设下**理论最快大约是哪些公式、数量级到什么程度**。

---

## 一、你该看哪几次运行？

脚本跑完后，每次都会在项目下生成目录：

```
outputs/runs/<时间戳>_benchmark_<配置名>.yaml/
```

举例（曾成功跑出完整指标的一次）：

- 目录：`outputs/runs/20260525_115120_benchmark_config.yaml/`

如果看到进程 **`Killed`（exit 137）**，多半是内存不够被系统杀掉，那一次目录里通常**没有完整**的 `trident_performance_benchmark.json`，请以成功跑完的目录为准。

同一目录里最直观的两个文件：

| 文件 | 适合做什么 |
|------|-------------|
| `trident_performance_benchmark.md` | 人类阅读：各阶段耗时、吞吐量、机型与内存摘要 |
| `trident_performance_benchmark.json` | 程序读取：与 `.md` 相同数据，结构化 |

此外还有 `performance_metrics.json`、`metrics.json`、`run.log` 等。

---

## 二、benchmark 里说的两个「每秒多少条流」分别是什么？

你的脚本会为整次运行统计两种常用口径：

### 1. 推理吞吐量（`flows_per_second_inference`）

近似公式：

$$
R_{\mathrm{infer}} \approx \frac{N_{\mathrm{stream}}}{T_{\mathrm{infer}}}
$$

- \(N_{\mathrm{stream}}\)：进入「流式阶段」后参与检测的流条数；  
- \(T_{\mathrm{infer}}\)：计时器里记在 **`stream_inference`** 上的那段「检测推理」耗时（不包含读 CSV）。

**白话**：这一阶段里，平均每秒钟能跑完多少次「把学生窗口交给模型判别」这档子事。**不看磁盘。**  
一次成功运行的例子（仅作量级参考）：约在 **数万条流/秒**（例如约 **\(6.7\times 10^{4}\)** flows/s）。

### 2. 端到端吞吐量（`flows_per_second_end_to_end`）

近似公式：

$$
R_{\mathrm{e2e}} \approx \frac{N_{\mathrm{total}}}{T_{\mathrm{wall}}}
$$

- \(N_{\mathrm{total}}\)：本条 run 一共处理了多少条流（若用了 `--max-rows` 会先截断再跑）；  
- \(T_{\mathrm{wall}}\)：从启动到整场结束的**墙上时钟**。

**白话**：把「读数据、预处理、初始化、画图导出、评测」全部都算进去的**平均吞吐**。磁盘和 CPU 预处理若很重，这个数字会远远低于上面的推理吞吐。例子量级可能在 **每秒几百到几千条**（视数据量与是否截断而定）。

---

## 三、时间主要花在哪？（性能消耗拆分思路）

端到端可以理解为多段流水线**首尾相接**。若近似按阶段加时（未做 IO 重叠时）：

$$
T_{\mathrm{wall}} \gtrsim T_{\mathrm{读入+预处理}} + T_{\mathrm{初始化}} + T_{\mathrm{流式推理}} + T_{\mathrm{导出/可视化}} + \cdots
$$

因此：

- **有磁盘**：往往 **`io_csv_read`、`io_preprocess`（统称数据准备）占比最大**。  
- **无磁盘**（假定数据已在内存）：主导项就变成 **预处理/特征、`classify_batch`、多 learner 顺序算 loss、导出** 里最慢的那一个。

从你的某次实测（25k 截断、`115120` 那次）可把「量级感」记在心上：

| 大致阶段 | 在「整趟耗时」里的角色 |
|----------|-------------------------|
| 读 CSV、解析、拼接、排序、过滤等 | **常是大头**（有磁盘时尤其明显） |
| `stream_inference`（推理段） | 往往只占 **_wall clock_ 很小的比例**——所以 \(R_{\mathrm{e2e}} \ll R_{\mathrm{infer}}\) |
| `init_*`（建 learner） | 与初始化规模有关 |
| `export_*`、`qualification_*` | 视配置与可视化打开情况 |

若要自己画饼图：用 `.json` 里 `stages_seconds` 各字段除以 `wall_clock_total` 即可。

---

## 四、「不考虑磁盘 IO」时：理论能多快？

下面**不包含**读取 CSV/U 盘的耗时；但**仍是你当前这套代码路径**下的讨论（PyTorch/Sklearn、`reconstruction_loss`、多 learner 等）。若重写实现（融合内核、少次 CPU↔GPU 往返），上界可以再抬。

### 4.1 实现里推理在算什么？

流式时每窗会调用 `classify_batch`；内部对每个 **learner** 调一次 **`reconstruction_loss(整窗矩阵)`**。  
 learner 若为 **AE**（自编码），结构可按代码注释概括为多层全连接：`35 → 256 → 128 → 64 → 32`再对称解码并带 skip（具体见 `tsieve.AutoEncoder`）。

对输入维度 \(d\)（你那趟特征是 **\(d \approx 35\)**），**纯前向**里占主导的是每层全连接的矩阵乘。常用估算每层 **\(2\sin s_{\mathrm{out}}\)** FLOPs/条样本（一条乘加计 2 次浮点）。

把各层相加，得到**每条样本、每个 learner、一次 AE 前向**的算术量量级：

$$
\phi \approx 2.24 \times 10^{5}\ \text{FLOPs/样本/learner}.
$$

若有 **\(L\)** 个 AE 在竞争，代码里是 **`L` 次顺序的前向**，则算术量近似：

$$
\text{GEMM FLOPs/窗（粗估）}
\approx L \cdot N_{\mathrm{win}} \cdot \phi,
$$

其中 \(N_{\mathrm{win}}\) 为窗口内样本数（例如配置里 **`window_size: 10000`** 就是大张量 GEMM）。

### 4.2 纯算力的「算术屋顶」（偏乐观）

设 GPU（或你希望用的数值类型）在**长期大批量 GEMM** 上能稳住的有效吞吐为 \(\eta\,P_{\mathrm{sust}}\)（\(P_{\mathrm{sust}}\) 为 sustained FLOPs/s，\(\eta\in(0,1]\) 为利用率），则在**算术饱和**的假说下：

$$
R_{\mathrm{FLOP}}^{\max}
\approx
\frac{\eta\, P_{\mathrm{sust}}}{L\,\phi}.
$$

代入 \(\phi \approx 2.24\times 10^{5}\)、**\(L=1\)**（很多轻量运行时确实只有一个 learner），再只对 **数量级** 举例：

若 \(\eta P_{\mathrm{sust}} \sim 10^{11}\) FLOPs/s（占位数量级），则  
\(R_{\mathrm{FLOP}}^{\max} \sim 10^{11}/(2.24\times10^5) \sim 10^{5}\) **量级**——再乐观一点可到 **几百万 flows/s** 的量级。**注意**：这是你**假想算力都吃满 GEMM**，和当前实测 **~\(\boldsymbol{10^4}\)** 级往往差很远，说明**当前路径远未吃满峰值算力**。

若 **\(L=2\)**，同一公式**大约除以 2**。

### 4.3 带宽与同步天花板（roofline）

实际 GPU 往往不是「算术算不动」，而是 **数据搬运（H2D/D2H）**、`detach().cpu().numpy()` 这类同步、或小算子碎片化导致算术强度上不去。roofline 思想可写成：

$$
R_{\mathrm{eff}}^{\max}
\approx
\min\left(
\frac{\eta_{\mathrm F} P_{\mathrm{sust}}}{L\phi},\;\;
\frac{\eta_{\mathrm B} \, BW_{\mathrm{eff}}}{\text{(每条流等效字节)}}
\right)
$$

\(BW_{\mathrm{eff}}\)：有效带宽；「每条流等效字节」与是否整窗拷贝、是否在 GPU 驻留、`float32` 等有关。  
不写死你机器的数字，结论是：**不重写代码时**，无磁盘也往往**不会让速度自动等于芯片宣传 TFLOPS**。

### 4.4 和最贴实现的「结构上界」

若暂不优化，仅去掉磁盘：

$$
T_{\mathrm{infer}}
\approx
\sum_{\mathrm{windows}}
\sum_{\ell=1}^{L}
\bigl(
T_{\mathrm{CPU},\ell}
+ T_{\mathrm{H2D},\ell}
+ T_{\mathrm{fwd},\ell}
+ T_{\mathrm{D2H},\ell}
\bigr)
+\text{Python 等小开销}.
$$

此时的 **「无磁盘理论最快」更接近「在当前实现上做 kernel/融合/砍掉 D2H 后的可改善空间」**：通常是对 \(R_{\mathrm{infer}}\) 的若干倍量级，再往上涨才碰到前一节的算术屋顶。**不会**因为「不测磁盘」就自动等价于片上峰值 TFLOPS。

---

## 五、如何自己复现一串数字？

在仓库根目录（`wkf/trident`）示例：

```bash
# 子集试跑（有 --max-rows）
python3 scripts/benchmark_trident_performance.py \
  --config configs/config.yaml --max-rows 25000

# 全量配置（时间与内存都大）
python3 scripts/benchmark_trident_performance.py --config configs/config.yaml
```

看结果：打开最新的 `outputs/runs/.../` 下的 `trident_performance_benchmark.md`。

---

## 六、一句话备忘

| 问题 | 一句话 |
|------|--------|
| 推理到底有多快（不看盘）？ | 看 **`flows_per_second_inference`** |
| 整趟为什么这么慢？ | 看 **`stages_seconds`** 里谁在吃 `wall_clock` |
| 芯片理论极限多高？ | 用 \(\,R_{\mathrm{FLOP}}^{\max} \approx (\eta P_{\mathrm{sust}})/(L\phi)\,\)，其中 \(\phi\sim 2.24\times 10^{5}\) |
| 和实测差很多正常吗？ | 正常：**小 AE + 当前实现**，往往远未算术饱和 |

本文中的公式是上界估计与量级说明，**不是你的机器上的保证值**；若要在你的 GPU 上把 \(\eta P_{\mathrm{sust}}\) 写实，需要对 **固定窗长、固定 \(L\) 的 AE 前向**做一次 profiler（例如 `torch.profiler`/`nsys`）再代入上式。

---

*文档路径：`docs/PERFORMANCE_BENCHMARK_EXPLAINED_zh.md`*
