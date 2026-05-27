# Suricata Service

独立的流量采集与 Redis Stream 写入服务。

当前阶段不实现 Trident 算法，也不依赖 `trident/` 或 `redis/` 目录代码。它只负责：

- 接收 Suricata CIC / EVE 风格 JSON
- 归一化五元组、时间戳和特征字段
- 写入 Redis Stream `suricata:cic_flow`

## Run

```bash
cd streamtrident_services/suricata
pip install -r requirements.txt
python -m app.main --config config/suricata.yaml
```

默认从 stdin 读取一行一个 JSON 对象。

