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
SURICATA_IFACE=eth0 make capture-start
```

Restart capture:

```bash
make capture-stop
SURICATA_IFACE=eth0 make capture-start
```

## Configuration

Environment variables:

- `SURICATA_IFACE`: host NIC to capture, default `eth0`
- `SURICATA_REDIS_HOST`: Redis host from host network, default `127.0.0.1`
- `REDIS_HOST_PORT`: Redis host port, default `16379`
- `SURICATA_REDIS_STREAM`: Redis queue key, default `suricata:cic_flow`
- `SURICATA_REDIS_OUTPUT_MODE`: Redis output mode, default `list`; set `stream` only for stream compatibility
- `SURICATA_REDIS_LIST_MAXLEN`: Redis list max length in `list` mode, default `100000`; set `0` to disable trimming
- `SURICATA_REDIS_STREAM_MAXLEN`: Redis stream maxlen when stream mode is enabled, default `1000000`
- `CIC_MODE`: CIC output mode, default `cic-flowmeter`
- `CIC_FLOW_TIMEOUT_US`: flow timeout, default `120000000`
- `CIC_ACTIVE_IDLE_THRESHOLD_US`: active/idle threshold, default `5000000`
- `SURICATA_CAPTURE_FILTER_CONFIG`: local capture-side BPF filter config, default `/etc/suricata-cic/capture-filter.json`
- `SURICATA_TCP_NEW_TIMEOUT`: TCP half-open flow timeout in seconds, default `10`
- `SURICATA_TCP_EMERGENCY_NEW_TIMEOUT`: emergency TCP half-open timeout in seconds, default `1`
- `SURICATA_RUNMODE`: Suricata runmode, default `workers`
- `SURICATA_EXTRA_ARGS`: extra Suricata CLI args

Optional local capture filter file example:

```json
{
  "enabled": true,
  "sourceIpRanges": [{"startIp": "172.16.0.0", "endIp": "172.16.255.255"}],
  "destIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
  "protocols": ["tcp", "udp", "icmp"],
  "extraBpf": "not arp and not broadcast and not multicast"
}
```

This file controls packet capture before Suricata creates flow state. It is
independent from `filter.json`, which only filters emitted `cic-flow` records.

Because the container uses `network_mode: host`, Redis is reached through the
host port (`127.0.0.1:${REDIS_HOST_PORT}`), not through the compose service name.

## Verify

```bash
cd streamtrident_services
make capture-logs
make capture-check
```

Or manually:

```bash
redis-cli -h 127.0.0.1 -p 16379 LLEN suricata:cic_flow
redis-cli -h 127.0.0.1 -p 16379 LRANGE suricata:cic_flow -1 -1
```
