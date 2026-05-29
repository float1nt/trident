# Trident 冷启动 / 推理双模式设计方案

## 1. 核心语义

Trident 运行链路拆成两个显式模式：

| 模式 | 职责 |
| --- | --- |
| `cold_start` | 使用良性流量建立初始学习器集合。冷启动学习器命名为 `COLD_*|BENIGN`。当学习进入稳定状态后，finalize 当前 session，并持久化冷启动学习器集合与 session runtime 元数据。 |
| `inference` | 纯推理运行模式。加载已 finalize 的冷启动学习器以及历史 `NEW_*` 学习器，对生产/攻击流量分类，并对未知行为创建新的 `NEW_*` 学习器。 |

本方案采用以下修正后的语义：

- 冷启动结束后，`COLD_*|BENIGN` 在推理阶段视为普通已加载学习器。
- 推理阶段不再对 `COLD_*|BENIGN` 做固定良性保护。
- 推理阶段不优先匹配良性学习器，继续保持当前 TSieve 逻辑：同一样本同时被良性与非良性学习器接受时，优先选择非良性学习器。
- 固定良性 audit 只在 cold_start finalize 时使用，用于固化冷启动结果。
- 推理阶段使用正常学习器 audit。新建的 `NEW_*` 走正常攻击审计；任何被主动刷新的 learner row 也不再套 baseline 保护捷径。

## 2. 当前问题

现有实现把冷启动和推理行为混在同一条路径里：

- 空 learner 状态会自动创建 `0000|UNLABELED`。
- `_maybe_finalize_cold_start()` 使用窗口大小启发式隐式 finalize。
- baseline 选择被压缩成单个 dominant learner。
- `build_learner_audit()` 会对 baseline learner 应用 `learner_baseline_benign_fixed`。
- inference 运行时仍可能误跑初始 learner 创建与冷启动 finalize 逻辑。

这会让实验和生产推理语义混乱：warmup、baseline policy、攻击 learner 创建同时发生在同一个 runtime loop 内。

## 3. 目标运行模式

### 3.1 `cold_start`

`cold_start` 是唯一允许创建 `COLD_*|BENIGN` 的模式。

行为要求：

- 允许空 learner 起步。
- 第一个有效窗口创建 `COLD_0|BENIGN`。
- 未知良性簇创建 `COLD_1|BENIGN`、`COLD_2|BENIGN` 等。
- cold_start 配置默认关闭 `small_learner_recluster_enabled`。
- 学习阶段允许对 COLD learner 做增量训练。
- 完成条件由学习稳定判定，不使用固定 flow 数作为硬截止。
- finalize 持久化：
  - `cold_start_finalized=true`
  - `session_baseline_learner`，即 dominant `COLD_*|BENIGN`，仅用于兼容展示和指标
  - `baseline_learner_names`，即全部 finalized `COLD_*|BENIGN`
  - cold-start flow/window 计数
  - finalize reason 与时间
- finalize 时对全部 `COLD_*|BENIGN` 执行一次固定良性 audit，作为冷启动产出快照。

### 3.2 `inference`

`inference` 不允许创建 baseline/cold-start learner。

行为要求：

- 当 `inference_require_cold_start=true` 时，启动前必须存在 finalized cold-start 元数据。
- 以下情况启动 fail-fast：
  - `pg_session_runtime.cold_start_finalized` 不为 true
  - 不存在 `COLD_*|BENIGN`
  - 必需的 model ref 无法加载
  - feature schema 或 model 元数据缺失/不一致
- `COLD_*|BENIGN` 作为普通已加载学习器参与分类。
- 历史 `NEW_*` 正常加载。
- 没有学习器接受的 flow 进入 unknown buffer，聚类后只能创建 `NEW_*`。
- inference 禁止调用 `_create_initial_learner`、`0000|UNLABELED` 路径、cold-start finalize 逻辑。
- 保持当前 TSieve 非良性优先匹配行为。

## 4. 配置

`TridentConfig` 增加：

```yaml
runtime_mode: inference                # cold_start | inference
cold_start_exit_on_complete: true
inference_require_cold_start: true

cold_start_stable_windows: 5
cold_start_stable_max_idle_seconds: 0
cold_start_min_learners: 1
cold_start_min_windows: 2
cold_start_min_flows: 0                # 可选安全下限，不是 50k 硬截止
```

说明：

- `cold_start_min_flows` 只是防止极小样本误 finalize 的安全阈值，必须可配置，不能替代稳定判定。
- cold-start compose/config 应默认设置 `small_learner_recluster_enabled: false`，除非后续单独设计 cold-start recluster 策略。

## 5. Worker CLI 与启动脚本

Worker 增加：

```bash
python -m app.worker --mode cold_start
python -m app.worker --mode inference
```

`--mode` 覆盖配置文件中的 `runtime_mode`。

脚本：

- `start-coldstart.sh`：使用 `--mode cold_start`
- `start-inference.sh`：使用 `--mode inference`

如果 inference 要消费 cold_start 产物，两个脚本必须使用同一个 `session_id`。

## 6. 引擎设计

将 `OnlineEngine.process_window()` 拆成显式分支：

```text
process_window(window):
  if runtime_mode == "cold_start":
    return process_window_cold_start(window)
  if runtime_mode == "inference":
    return process_window_inference(window)
```

### 6.1 Cold-Start 分支

处理流程：

1. 预处理 records，并更新 feature schema。
2. 如果没有 learner，创建 `COLD_0|BENIGN`。
3. 用已有 COLD learner 分类。
4. unknown 样本进入 tMagnifier。
5. unknown 簇 promotion 时创建 `COLD_N|BENIGN`。
6. learning 阶段允许对 COLD learner 增量训练。
7. 更新 cold-start tracker。
8. 满足稳定条件时 finalize。

### 6.2 稳定完成条件

引入 `ColdStartTracker`，显式记录：

- `windows_processed`
- `cold_start_flow_count`
- `stable_streak`
- `last_learning_activity_at`
- `last_learning_activity_window`
- `finalized`

学习活动定义：

- 创建一个或多个 `COLD_*|BENIGN`
- learning 阶段对 learner 执行重训/增量训练

稳定窗口定义：

- 本窗没有新建 `COLD_*|BENIGN`
- 本窗没有重训

为避免“良性流持续进入导致每窗都重训，从而永远无法稳定”，cold_start 应采用两阶段状态机：

```text
learning:
  创建 COLD learner，并允许训练/增量更新
  满足 min guards 后进入 observing

observing:
  冻结 COLD 模型更新
  继续分类和 unknown 聚类
  如果又创建新 COLD learner，回到 learning
  如果 stable_streak 达标，finalize

finalized:
  输出最终 learner rows / snapshots / runtime update
  如配置要求，等待持久化与 ack 完成后优雅退出 worker
```

finalize 条件必须同时满足：

1. `learner_count >= cold_start_min_learners`
2. `windows_processed >= cold_start_min_windows`
3. `cold_start_flow_count >= cold_start_min_flows`
4. `stable_streak >= cold_start_stable_windows`
5. 如果配置了 idle 秒数，idle 条件也满足

### 6.3 Finalize

`_finalize_cold_start_session(reason)` 不应在 engine 内直接写 DB，而是产出持久化请求。

finalize 输出：

- 全部 `COLD_*|BENIGN` learner rows
- `reason=cold_start_complete` 的 snapshot requests
- runtime metadata update
- `cold_start_complete` 结构化事件 payload

dominant baseline 选择：

- `session_baseline_learner` = train sample count 最大的 `COLD_*|BENIGN`
- `baseline_learner_names` = 所有 `COLD_*|BENIGN`

固定良性 audit：

- 只在 finalize rows 上应用。
- inference 中不复用该策略。

### 6.4 Inference 分支

处理流程：

1. 使用已加载 schema 预处理 records。
2. 即使 learner 为空，也不创建 initial learner。
3. 使用现有 TSieve 语义分类，包括非良性优先匹配。
4. unknown 样本进入 tMagnifier。
5. unknown 簇 promotion 时创建 `NEW_N`。
6. 增量更新按现有 gate 作用于 `NEW_*`。
7. `COLD_*|BENIGN` 不再受固定良性 audit 保护。
8. 不运行 cold-start tracker/finalize 逻辑。

首版建议：

- `COLD_*|BENIGN` 作为普通已加载 learner 参与分类。
- 不主动刷新 COLD 的 finalize audit rows，除非后续设计明确的 runtime update 路径。
- 新的运行时/攻击行为 learner 全部命名为 `NEW_*`。

## 7. Learner 命名

用 prefix 数字扫描替代基于 `len(self.tsieve.learners)` 的命名。

当前 `NEW_{len(self.tsieve.learners)}` 在加载历史 learner、删除小 learner、或存在多个 COLD learner 后可能撞名。

新增 helper：

```text
next_learner_name(prefix):
  扫描已有 learner names
  解析该 prefix 下的数字后缀
  返回 prefix + (max_suffix + 1)
```

示例：

- 已有 `COLD_0|BENIGN`、`COLD_1|BENIGN` -> 下一个 `COLD_2|BENIGN`
- 已有 `NEW_0`、`NEW_7` -> 下一个 `NEW_8`

## 8. Quality 层

将规则审计划分成两个 API：

```text
build_learner_audit(...)
  普通 audit 路径。
  用于 inference / NEW learner。
  不应用 cold-start baseline 保护。

apply_cold_start_benign_audit(...)
  finalize-only 路径。
  输出固定 BENIGN_NORMAL 规则，可附带污染检测证据。
  只由 cold_start finalize 调用。
```

移除 inference 对以下逻辑的依赖：

- `learner_baseline_benign_fixed`
- baseline 启发式吸收
- 使用单个 dominant baseline 作为保护选择器

保留 `session_baseline_learner`，但仅用于展示和兼容指标。

## 9. Session Runtime 持久化

新增迁移：

```sql
CREATE TABLE IF NOT EXISTS pg_session_runtime (
  session_id VARCHAR(256) PRIMARY KEY,
  runtime_mode VARCHAR(32),
  cold_start_finalized BOOLEAN DEFAULT FALSE,
  cold_start_flow_count BIGINT DEFAULT 0,
  cold_start_windows_processed BIGINT DEFAULT 0,
  cold_start_finalize_reason VARCHAR(32),
  session_baseline_learner VARCHAR(512),
  baseline_learner_names JSONB,
  cold_start_stable_streak BIGINT DEFAULT 0,
  cold_start_finalized_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

新增 `SessionRuntimeRepository`：

- `get(session_id)`
- `upsert_cold_start_progress(...)`
- `mark_cold_start_finalized(...)`
- `validate_inference_ready(session_id, learners)`

inference 启动校验必须同时检查 runtime 元数据与可加载 learner rows。

## 10. Worker 持久化边界

engine 尽量保持轻副作用：

- engine 返回 `WindowResult`
- `WindowResult` 可包含：
  - `snapshot_requests`
  - `runtime_update`
  - `control_flags`，例如 `cold_start_completed`
  - 结构化 observability events

worker 持久化顺序：

1. snapshots / learner upsert
2. runtime metadata update
3. assignments
4. Redis metrics/events
5. Redis ack
6. 如果配置了 `cold_start_exit_on_complete`，最后再退出

这样可以避免日志显示 cold-start complete 或 worker 退出早于最后一窗持久化。

## 11. 可观测性

所有 worker 事件都应携带 `runtime_mode`。

Cold-start 事件：

| 事件 | 时机 | 关键字段 |
| --- | --- | --- |
| `cold_start_window_state` | 每个 cold-start 窗口 | `window_index`, `learner_count`, `new_learner_names`, `retrained_learner_names`, `unknown_count`, `stable_streak`, `phase`, `cold_start_flow_count` |
| `cold_start_learner_snapshot` | 每 N 窗或 learner 变化时 | `learners[]`，包含 name、sample count、threshold、creation/last seen windows |
| `cold_start_stability_tick` | stable streak 递增时 | `stable_streak`, `required_stable_windows`, `idle_seconds`, `phase` |
| `cold_start_complete` | finalize 时 | `baseline_learner`, `baseline_learner_names`, `total_flows`, `total_windows`, `finalize_reason` |

`window_processing_finished` 应包含：

- `runtime_mode`
- `new_learner_count`
- `updated_learner_count`
- cold_start 下的 `cold_start_phase`
- cold_start 下的 `cold_start_finalized`

运维观察示例：

```bash
tail -f trident/logs-test/worker.log | grep -E 'cold_start_|window_processing_finished'
```

## 12. Assignment / 实验阶段隔离

cold_start 与 inference 可以共享 `session_id`，但查询必须能区分阶段。

最低要求：

- 在 `assignment_meta` 中写入 `runtime_mode`

更推荐的 schema 改造：

- 在 `ch_flow` 增加 `runtime_mode LowCardinality(String)`

实验脚本统计 inference 指标时，应按 `runtime_mode='inference'` 或记录的 inference 起始时间/window 过滤，避免 warmup 良性流混入攻击评估。

## 13. API

可选接口：

```text
GET /runtime/status
POST /runtime/cold-start/complete
```

`POST /runtime/cold-start/complete`：

- 仅允许在 `cold_start` 模式调用。
- 使用 `reason=manual` finalize。
- 除非显式 admin force，否则至少要求存在一个 `COLD_*|BENIGN`。

## 14. 测试要点

| 场景 | 断言 |
| --- | --- |
| Config mode loading | `runtime_mode`、cold-start 阈值、inference guard 可从 YAML 读取，CLI override 生效 |
| Inference fail-fast | 没有 finalized runtime row 或没有可加载 `COLD_*|BENIGN` 时，worker exit 2 并输出明确日志 |
| Cold-start initial learner | 第一个 cold-start 窗口创建 `COLD_0|BENIGN`，不创建 `0000|UNLABELED` |
| Cold-start unknown promotion | unknown 良性簇创建 `COLD_N|BENIGN` |
| Cold-start stable completion | observing 阶段 stable streak 达标后 finalize |
| Cold-start early completion guard | 无 learner、仅 1 个小窗口、未满足 min guards 时不 finalize |
| Finalize audit | 所有 `COLD_*|BENIGN` finalize rows 都写入固定良性 audit |
| Inference no baseline creation | 空 inference engine 不创建 initial learner |
| Inference unknown promotion | unknown 簇只创建 `NEW_N`，不创建 `COLD_N|BENIGN` |
| Inference audit semantics | inference 不应用固定良性保护策略 |
| Naming | 已有 `NEW_7` 时下一个是 `NEW_8`；已有 COLD 0/1 时下一个是 `COLD_2|BENIGN` |
| Logging | 可 grep 到 `cold_start_window_state` 与 `cold_start_complete` |
| Persistence ordering | completion exit 发生在 snapshots/runtime/assignments/ack 之后 |

## 15. 实施顺序

1. 增加 config 字段与 CLI mode override。
2. 增加 `pg_session_runtime` migration 与 repository。
3. 增加 inference 启动校验。
4. 拆分 quality API：普通 audit 与 finalize-only benign audit。
5. 增加 learner 命名 helper。
6. 拆分 `OnlineEngine.process_window()` 为 cold-start / inference 分支。
7. 增加 `ColdStartTracker` 与 learning/observing/finalized 状态机。
8. 将 cold-start finalize 结果通过 `WindowResult` 传给 worker。
9. worker 持久化 runtime updates。
10. 增加日志与 `runtime_mode` metrics。
11. 增加启动脚本与 compose/config 覆盖。
12. 更新实验指南与 `run_accuracy_eval.py`，改为等待 `cold_start_complete`。

## 16. 风险与防护

| 风险 | 防护 |
| --- | --- |
| 对已 finalized session 重复 cold_start | 要求显式 reset/clear-session 选项 |
| 极小 warmup 误 finalize 弱 learner | 使用 min windows、min learners、可选 min flows |
| 因持续重训导致稳定条件永远达不到 | 使用 learning -> observing，observing 阶段冻结模型更新来测稳定 |
| 历史 `0000|UNLABELED` session | 默认不自动兼容；如有需要单独提供迁移工具 |
| 冷启动流量混入攻击 | finalize-only 污染检测可告警，但运维流程必须保证 cold-start 输入是良性 |
| 实验指标混入 warmup 流量 | 写入/过滤 `runtime_mode` |
| inference 启动时 model ref 损坏 | 消费 Redis 前校验 learner 可加载性 |

