# Testing And Benchmark Harnesses

This directory documents test and benchmark responsibilities. Current executable
test harness code remains in `trident_demo/stress/` to preserve imports and CLI
compatibility.

## Stress Harness

Current command:

```bash
python3 -m trident_demo.stress trident_demo/stress/configs/e2e.yaml
```

Purpose:

- Start local Redis and Suricata containers for an experiment run.
- Replay pcap traffic with `tcpreplay`.
- Run Trident benchmark against the Redis stream.
- Collect Redis, Docker, Suricata, replay, and Trident metrics.
- Write `trident_demo/testing/outputs/stress/<run_id>/`.

This is an experiment harness, not the production deployment architecture.

## Smoke Checks

Useful lightweight checks:

```bash
python3 -m compileall trident_demo/runtime trident_demo/cli.py
python3 -m trident_demo --help
python3 -m trident_demo online --help
python3 -m trident_demo run --help
```

## Existing Locations

```text
trident_demo/stress/          E2E stress controller and configs
trident_demo/benchmark/       performance recorder and resource metrics
trident_demo/testing/outputs/stress/  generated stress results
```
