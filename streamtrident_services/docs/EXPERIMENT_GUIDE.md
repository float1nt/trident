# StreamTrident 学习器聚合准确率实验指南

本文档用于在虚拟机上复现实验脚本 `experiments/streamtrident_accuracy_eval/run_accuracy_eval.py` 的黑盒准确率评估流程。该流程不修改 `streamtrident_services` 项目代码，只通过外部脚本启动依赖、生成临时 Trident 配置、注入 CICIDS CSV flow，并从 ClickHouse 回读学习器分配结果计算准确率。

## 实验目标

验证实时流推理后，具有相同流量类型的 flow 是否会被聚到同一批学习器里。

评估方法：

1. 每条测试 flow 都带有实验标签，例如 `BENIGN`、`PORTSCAN`、`DDOS`、`DOS_HULK`、`SYN`、`DRDOS_DNS`、`DRDOS_NTP`。
2. Trident 在线 worker 不使用这些标签，只消费 Redis Stream 中的 `features_json`、五元组字段和时间字段。
3. 实验结束后，从 ClickHouse 的 `ch_flow` 表取回每条 flow 的 `assigned_learner`。
4. 对每个 learner 统计其中占比最高的标签，作为这个 learner 的预测类型。
5. 再把 learner 主标签回填到每条 flow，计算准确率。

这里的“聚合度”对应报告里的：

- `assigned_coarse_acc`：只统计成功分配到 learner 的 flow，按合并后的攻击大类计算准确率。
- `coarse_acc`：把 unknown 也算错，按合并后的攻击大类计算准确率。
- `assigned_strict_acc`：只统计成功分配到 learner 的 flow，按原始细标签计算准确率。
- `strict_acc`：把 unknown 也算错，按原始细标签计算准确率。

之前讨论的“UDP 九十多、TCP 约 83”指的是这套学习器主标签回填口径下的聚合准确率，不是旧实验里的风险检测率。

## 数据集要求

脚本默认读取以下 CSV：

```text
data/
├── cic2017/
│   ├── monday.csv
│   ├── friday.csv
│   └── wednesday.csv
└── cicids2019/
    ├── Syn.csv
    ├── DrDoS_DNS.csv
    └── DrDoS_NTP.csv
```

默认抽样规模：

| 标签 | 数据文件 | CSV Label | 测试条数 |
|---|---|---|---:|
| `BENIGN` | `data/cic2017/monday.csv` | `BENIGN` | 20000 |
| `PORTSCAN` | `data/cic2017/friday.csv` | `Portscan` | 10000 |
| `DDOS` | `data/cic2017/friday.csv` | `DDoS` | 10000 |
| `DOS_HULK` | `data/cic2017/wednesday.csv` | `DoS Hulk` | 10000 |
| `SYN` | `data/cicids2019/Syn.csv` | `Syn` | 10000 |
| `DRDOS_DNS` | `data/cicids2019/DrDoS_DNS.csv` | `DrDoS_DNS` | 10000 |
| `DRDOS_NTP` | `data/cicids2019/DrDoS_NTP.csv` | `DrDoS_NTP` | 10000 |

默认还会先注入 `50000` 条 `BENIGN` warmup flow，用来冷启动 benign baseline。warmup 不参与准确率计分。

## 评估标签

脚本同时计算 strict 和 coarse 两套标签。

strict 标签保持原始实验类型：

```text
BENIGN
PORTSCAN
DDOS
DOS_HULK
SYN
DRDOS_DNS
DRDOS_NTP
```

coarse 标签把相近攻击合并，降低“同一行为家族被拆成多个细标签”带来的噪声：

```text
BENIGN -> BENIGN
PORTSCAN -> PORTSCAN
DDOS + DOS_HULK -> DOS_DDOS
SYN -> SYN_FLOOD
DRDOS_DNS + DRDOS_NTP -> DRDOS_UDP_FAMILY
```

## 环境准备

在虚拟机中进入仓库根目录：

```bash
cd /path/to/trident
```

建议使用 Python 虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r streamtrident_services/trident/requirements.txt
python -m pip install pandas requests redis PyYAML psycopg[binary]
```

确认 Docker 可用：

```bash
docker version
docker compose version
```

确认默认端口未被占用：

```text
Redis: 127.0.0.1:16379
ClickHouse HTTP: 127.0.0.1:18123
PostgreSQL: 127.0.0.1:15432
```

## 推荐执行方式

直接从仓库根目录运行：

```bash
python experiments/streamtrident_accuracy_eval/run_accuracy_eval.py \
  --force-split \
  --benign-warmup 50000 \
  --timeout 3600
```

`--force-split` 会固定执行三组实验：

1. `mixed_tcp_udp`：TCP 和 UDP 混合输入。
2. `tcp_only`：只输入 `Protocol=6` 的 flow。
3. `udp_only`：只输入 `Protocol=17` 的 flow。

脚本会自动执行：

1. `docker compose -f streamtrident_services/compose.yaml up -d redis clickhouse postgres`
2. 等待 Redis、ClickHouse、PostgreSQL 可用。
3. 为每组实验生成独立 `session_id` 和临时配置。
4. 执行数据库 migration。
5. 启动本地 Python worker。
6. 先注入 benign warmup。
7. 再注入测试集 flow。
8. 等待 ClickHouse 写满预期行数。
9. 停止 worker。
10. 生成评估报告。

如果依赖服务已经提前启动，可以使用：

```bash
python experiments/streamtrident_accuracy_eval/run_accuracy_eval.py \
  --skip-deps \
  --force-split \
  --benign-warmup 50000 \
  --timeout 3600
```

## 输出目录

默认输出到：

```text
outputs/streamtrident_accuracy_eval/<run_id>/
```

每次执行都会创建独立 run 目录。目录结构类似：

```text
outputs/streamtrident_accuracy_eval/<run_id>/
├── manifest.json
├── all_summaries.json
├── REPORT.md
├── mixed_tcp_udp/
│   ├── trident_eval_config.yaml
│   ├── warmup_benign.csv
│   ├── flow_labels.csv
│   ├── assignments.csv
│   ├── joined_predictions.csv
│   ├── learner_summary.csv
│   ├── confusion_strict.json
│   ├── confusion_coarse.json
│   ├── summary.json
│   └── worker.log
├── tcp_only/
└── udp_only/
```

最先看的文件：

- `REPORT.md`：整体表格汇总。
- `all_summaries.json`：完整机器可读结果。
- `*/learner_summary.csv`：每个 learner 的主标签、纯度、协议分布和标签分布。
- `*/joined_predictions.csv`：每条 flow 的真实标签、分配 learner、回填预测标签。
- `*/worker.log`：Trident worker 运行日志。

## 关键结果怎么看

打开：

```bash
cat outputs/streamtrident_accuracy_eval/<run_id>/REPORT.md
```

重点看表格中的：

```text
experiment
assigned_coarse_acc
assigned_strict_acc
unknown_rate
learners
```

建议判断顺序：

1. 先看 `udp_only` 的 `assigned_coarse_acc`，它对应 UDP 单独分流后的聚合度。
2. 再看 `tcp_only` 的 `assigned_coarse_acc`，它对应 TCP 单独分流后的聚合度。
3. 再看 `mixed_tcp_udp`，判断混合输入是否因为 TCP/UDP 共用学习器池导致互相污染。
4. 如果 `unknown_rate` 很高，优先检查 worker 是否处理完成、ClickHouse 写入是否超时、配置阈值是否过严。
5. 如果 `assigned_coarse_acc` 高但 `assigned_strict_acc` 低，说明同一攻击家族可以聚在一起，但细分攻击类型仍混杂。

## 实验脚本生成的 Trident 配置

每组实验都会生成自己的 `trident_eval_config.yaml`。核心配置包括：

```yaml
consumer_mode: best_effort
best_effort_start_id: <实验开始前 Redis Stream 最新 ID>
read_count: 2048
window_size: 1000
feature_profile: compact_stats_no_env
algorithm_backend: ae
cpu_only: true
seed: 42
init_epochs: 5
new_class_epochs: 4
increment_epochs: 1
preprocessing_enabled: true
preprocessing_drop_all_zero: false
small_learner_recluster_enabled: false
```

这个配置是实验脚本临时生成的，不会覆盖项目中的 `streamtrident_services/trident/config/trident.yaml` 或 `streamtrident_services/docker/trident.yaml`。

## 数据注入格式

脚本不会把 CSV 原样塞给 Trident，而是转换成 Redis Stream 字段：

```text
event_type=cic_flow
session_id=<本次实验 session>
flow_uid=<实验唯一 flow id>
event_time=<CSV Timestamp 转 UTC>
src_ip=<Src IP>
dst_ip=<Dst IP>
src_port=<Src Port>
dst_port=<Dst Port>
protocol=<Protocol>
source_flow_id=<Flow ID>
features_json=<CSV 中所有数值特征组成的 JSON>
raw_event_json=<实验标签和 flow_uid 元数据>
```

Trident worker 只读取在线推理需要的字段。实验标签只保存在外部 `flow_labels.csv` 和 `raw_event_json` 中，用于结束后评估，不参与模型推理。

## 常见问题

### 1. 数据文件找不到

检查路径是否与脚本默认一致：

```bash
ls data/cic2017/monday.csv
ls data/cic2017/friday.csv
ls data/cic2017/wednesday.csv
ls data/cicids2019/Syn.csv
ls data/cicids2019/DrDoS_DNS.csv
ls data/cicids2019/DrDoS_NTP.csv
```

如果虚拟机里的文件名不同，需要修改 `run_accuracy_eval.py` 顶部 `STRICT_LABEL_SPECS` 中的路径和 label 名称。

### 2. 等待处理超时

先看当前处理进度：

```bash
curl -sS 'http://default:trident@127.0.0.1:18123/?query=SELECT%20session_id,count()%20FROM%20ch_flow%20GROUP%20BY%20session_id%20ORDER%20BY%20count()%20DESC%20LIMIT%2010'
```

再看对应实验的 worker 日志：

```bash
tail -n 200 outputs/streamtrident_accuracy_eval/<run_id>/<experiment>/worker.log
```

如果 ClickHouse 写入慢，可以先把 `--timeout` 调大到 `7200`。

### 3. Redis 中有历史数据会不会干扰

脚本会在每组实验开始前读取 Redis Stream 的 `last-generated-id`，并把它写入 `best_effort_start_id`。worker 只从这个 ID 之后消费，因此历史数据通常不会干扰。

每组实验还有独立 `session_id`，ClickHouse 查询也按 `session_id` 过滤。

### 4. mixed 效果明显低于 tcp_only/udp_only

这说明 TCP 和 UDP 在同一学习器池里可能互相污染。这个实验本身就是为了暴露这个问题，所以报告里会同时保留 mixed、tcp_only、udp_only 三组结果。

### 5. UDP 或 TCP 某组没有足够数据

脚本会按 `Protocol` 字段过滤。若某个标签在指定协议下不足 `10000` 条，实际注入数量会低于目标值。以 `summary.json` 中的 `dataset.per_label` 为准。

## 复现实验时需要记录的信息

把以下内容保存给后续对比：

```text
git commit:
run_id:
虚拟机 CPU / 内存:
Docker 版本:
Python 版本:
数据集文件来源:
REPORT.md:
all_summaries.json:
tcp_only/learner_summary.csv:
udp_only/learner_summary.csv:
mixed_tcp_udp/learner_summary.csv:
```

## 预期现象

正常情况下，`udp_only` 的 coarse 聚合准确率应明显高于 mixed；`tcp_only` 通常比 UDP 更难，可能落在八成左右。若重新跑出的 TCP/UDP 都显著偏低，优先检查三点：

1. CSV 特征列是否完整，尤其是 CICIDS 数值特征是否进入 `features_json`。
2. `worker.log` 是否有 ClickHouse 写入、模型训练或 Redis 消费异常。
3. `learner_summary.csv` 是否出现大量 `__UNKNOWN__` 或单个 baseline 吃掉大量攻击流。

