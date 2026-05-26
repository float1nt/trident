# Redis Service

Redis is the stream broker between Suricata and Trident.

## Responsibility

- Receive flow feature records from Suricata.
- Buffer backlog when Trident is slower than Suricata.
- Provide consumer group state for Trident.
- Expose stream health metrics such as length and pending entries.

## Primary Stream

```text
suricata:cic_flow
```

## Recommended Output Streams

The current implementation mainly writes files for benchmark output. A
production service should eventually emit online results to streams such as:

```text
trident:assignments
trident:alerts
trident:metrics
```

## Health Signals

Important Redis-side metrics:

- `XLEN suricata:cic_flow`: backlog size.
- `XPENDING`: unacked consumer-group messages.
- Redis memory usage.
- Redis ops/sec.

## Current Demo Mapping

The demo preflight can start Redis via docker compose for local experiments, but
the `online` command now assumes Redis is already running:

```bash
python3 -m trident_demo online --config trident_demo/configs/online.yaml
```

For local demo only:

```bash
python3 -m trident_demo online --start-redis
```
