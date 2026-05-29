# Redis Service

独立 Redis 服务目录。

这个目录只负责 Redis 本身和队列状态管理，不引用 `suricata/` 或 `trident/` 的代码。默认队列类型是 Redis list；`ensure-group` 在 list 模式下是无操作，用于兼容 compose 启动流程。

## Run Redis

```bash
cd streamtrident_services/capture/redis
docker compose up -d
```

## Queue Admin

```bash
pip install -r requirements.txt
python -m app.main ensure-group --config config/redis.yaml
python -m app.main status --config config/redis.yaml
```
