# Redis Service

独立 Redis Stream 服务目录。

这个目录只负责 Redis 本身和 Stream 管理，不引用 `suricata/` 或 `trident/` 的代码。

## Run Redis

```bash
cd streamtrident_services/redis
docker compose up -d
```

## Stream Admin

```bash
pip install -r requirements.txt
python -m app.main ensure-group --config config/redis.yaml
python -m app.main status --config config/redis.yaml
```

