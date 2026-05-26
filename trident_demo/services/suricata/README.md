# Suricata Service

Suricata is the upstream producer in the target deployment.

## Responsibility

- Run independently from Trident.
- Capture traffic from a switch mirror port, gateway interface, or equivalent sensor point.
- Produce flow / CIC feature records.
- Write feature records to Redis Stream.

## Input

```text
network interface / mirror traffic
```

## Output

Default stream:

```text
suricata:cic_flow
```

Expected event type:

```text
cic_flow
```

## Data Contract

Each Redis message should represent one flow feature record. The Trident Redis
loader accepts common aliases and normalizes them to CIC-style names:

```text
src_ip      -> Src IP
dst_ip      -> Dst IP
src_port    -> Src Port
dst_port    -> Dst Port
protocol    -> Protocol
timestamp   -> Timestamp
label       -> Label
```

Production traffic may not have `Label`; Trident fills it with
`0000|UNLABELED` when absent.

## Current Demo Mapping

The E2E stress harness can start a demo Suricata container:

```bash
python3 -m trident_demo.stress trident_demo/stress/configs/e2e.yaml
```

That path is for test and benchmark orchestration. In production, Suricata should
be deployed and supervised as its own service.
