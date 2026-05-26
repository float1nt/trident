# Services View

This directory documents the deployment-service view of `trident_demo`.

It does not replace the Python package layout yet. The current code still keeps
shared modules such as `core/`, `io/`, `runtime/`, `pipeline/`, and `stress/` at
the top level to preserve existing imports and CLI compatibility.

Service responsibilities:

```text
services/suricata/  Suricata flow/CIC feature producer
services/redis/     Redis Stream broker and backlog layer
services/trident/   Trident online consumer and model runtime
```

Related runtime command:

```bash
python3 -m trident_demo online --config trident_demo/configs/online.yaml
```

Related stress command:

```bash
python3 -m trident_demo.stress trident_demo/stress/configs/e2e.yaml
```

The stress command is a test harness. It should not be treated as the production
service layout.
