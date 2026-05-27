# StreamTrident Backend

独立实时流处理后端设计方案仓库。

当前仅包含架构与设计文档，尚未实现代码。完整设计见：

- [`docs/DESIGN.md`](docs/DESIGN.md)
- [`docs/P0_IMPLEMENTATION_PLAN.md`](docs/P0_IMPLEMENTATION_PLAN.md)
- [`docs/RULE_ENGINE_DESIGN.md`](docs/RULE_ENGINE_DESIGN.md)

## 范围

- 三模块独立：Suricata（采集写入）、Redis Bridge（Stream 桥接）、Trident（在线推理 + 5 个读 API）
- 写库：`PersistenceService` 统一协调 `ch_flow` + `pg_learner`，并在学习器更新时追加 `pg_learner_snapshot`
- 纯 Redis Stream 实时链路，无静态文件、无标签、无可视化

## 不在范围内

- 批处理 / CSV / PCAP 回放
- 压测脚本、benchmark 工具
- 前端与 audit JSON 导出
