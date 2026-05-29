# Suricata CIC Service

This service runs the modified Suricata binary and captures packets from a host
network interface. It emits CICFlowMeter-style `cic-flow` events directly to
Redis list `suricata:cic_flow` by default.

## Runtime

The image packages prebuilt runtime files from this repository:

- `runtime/bin/suricata`
- `runtime/etc/suricata/suricata.yaml`
- `runtime/etc/suricata/classification.config`
- `runtime/etc/suricata/reference.config`
- `runtime/rules/empty.rules`

The entrypoint generates a live Suricata config that enables Redis EVE output:

```text
network interface -> modified Suricata -> Redis list -> Trident worker
```

## Start

Set the capture interface and start the compose stack:

```bash
cd streamtrident_services
SURICATA_IFACE=eth0 make up
```

Restart only capture:

```bash
SURICATA_IFACE=eth0 make restart-capture
```

## Configuration

Environment variables:

- `SURICATA_IFACE`: host NIC to capture, default `eth0`
- `SURICATA_REDIS_HOST`: Redis host from host network, default `127.0.0.1`
- `REDIS_HOST_PORT`: Redis host port, default `16379`
- `SURICATA_REDIS_STREAM`: Redis queue key, default `suricata:cic_flow`
- `SURICATA_REDIS_OUTPUT_MODE`: Redis output mode, default `list`; set `stream` only for stream compatibility
- `SURICATA_REDIS_STREAM_MAXLEN`: Redis stream maxlen when stream mode is enabled, default `1000000`
- `CIC_MODE`: CIC output mode, default `cic-flowmeter`
- `CIC_FLOW_TIMEOUT_US`: flow timeout, default `120000000`
- `CIC_ACTIVE_IDLE_THRESHOLD_US`: active/idle threshold, default `5000000`
- `SURICATA_RUNMODE`: Suricata runmode, default `workers`
- `SURICATA_EXTRA_ARGS`: extra Suricata CLI args

Because the container uses `network_mode: host`, Redis is reached through the
host port (`127.0.0.1:${REDIS_HOST_PORT}`), not through the compose service name.

## Verify

```bash
docker logs -f streamtrident-suricata-cic
redis-cli -h 127.0.0.1 -p 16379 LLEN suricata:cic_flow
redis-cli -h 127.0.0.1 -p 16379 LRANGE suricata:cic_flow 0 0
```
