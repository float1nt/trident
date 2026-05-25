# Suricata CIC Redis Live

This directory runs the modified Suricata as a live CICFlowMeter-style feature
producer and sends `event_type=cic_flow` EVE JSON events to Redis Stream.

## Layout

- `docker-compose.yml`: Redis plus Suricata services.
- `runtime/`: copied modified Suricata executable and config used by Docker.
- `docker/Dockerfile`: packages runtime files; it does not compile Suricata.
- `docker/entrypoint.sh`: generates live Redis config and starts packet capture.
- `scripts/start.sh`: build image if needed and start the stack.
- `scripts/monitor.sh`: show container status, Redis stream status, Suricata logs.
- `scripts/stop.sh`: stop the stack.
- `logs/`: Suricata `suricata.log` and `stats.log`.

## Quick Start

```bash
cd /home/Suricata/suricata-cic-redis-live
cp .env.example .env
```

Edit `.env` and set `IFACE` to the capture NIC. To auto-detect the default
route NIC, `scripts/start.sh` will create `.env` if it does not already exist.

Refresh runtime files after rebuilding `/home/Suricata/suricata`:

```bash
./scripts/sync_runtime.sh
./scripts/build_image.sh
```

```bash
./scripts/start.sh
./scripts/monitor.sh
```

Redis Stream defaults:

```text
host: 127.0.0.1
port: 6379
stream: suricata:cic_flow
```

Read events manually:

```bash
docker run --rm --network host redis:7-alpine \
  redis-cli -h 127.0.0.1 -p 6379 XREVRANGE suricata:cic_flow + - COUNT 5
```

Stop:

```bash
./scripts/stop.sh
```

## Notes

- The Suricata container uses `network_mode: host` and captures directly from
  the host NIC named by `IFACE`.
- The Redis container also uses host networking and binds to `127.0.0.1`.
- The Suricata image uses the copied executable at `runtime/bin/suricata`.
  It starts quickly and does not require source code inside the image. After
  changing C code, rebuild Suricata on the host, then sync and rebuild the
  small runtime image:

```bash
./scripts/sync_runtime.sh
./scripts/build_image.sh
docker compose up -d suricata-cic
```

- Redis EVE output requires the copied Suricata binary to be built with
  `--enable-hiredis`. `scripts/sync_runtime.sh` warns if the binary is not
  linked with hiredis.

- Logs are available through both Docker and local files:

```bash
docker logs -f suricata-cic-live
tail -f /home/Suricata/suricata-cic-redis-live/logs/suricata.log
tail -f /home/Suricata/suricata-cic-redis-live/logs/stats.log
```
