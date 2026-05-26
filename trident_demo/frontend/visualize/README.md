# Trident Demo Stress Dashboard

React + Vite 版压测可视化，位于 `trident_demo/frontend/visualize/`。

## 启动

```bash
cd trident_demo/frontend/visualize
npm install
npm run dev
```

默认地址：

```text
http://127.0.0.1:5184
```

## 数据来源

Vite 插件 `vite.stressDataPlugin.ts` 直接读取：

```text
trident_demo/testing/outputs/stress/<run_id>/
```

展示内容包括：

- 压测 run 列表和状态
- `stress_summary.json` 中的阶段耗时
- `redis_metrics.json` 中的 Redis XLEN、ops、内存曲线
- `docker_metrics.json` 中的 Suricata 容器 CPU / 内存曲线
- `trident_performance_benchmark.json` 或 summary 内嵌 benchmark 中的吞吐和资源指标
