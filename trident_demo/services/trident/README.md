# Trident Service

Trident is the online Redis consumer and anomaly detection runtime.

## Responsibility

- Consume flow feature records from Redis Stream.
- Apply runtime preprocessing.
- Build and align feature matrices.
- Initialize learners.
- Classify incoming windows.
- Run the full online flow: UNKNOWN buffering, DBSCAN clustering, new learner
  creation, and incremental learner updates.

## Current Command

```bash
python3 -m trident_demo online --config trident_demo/configs/online.yaml
```

Useful overrides:

```bash
python3 -m trident_demo online \
  --redis-url redis://127.0.0.1:6379/0 \
  --redis-stream suricata:cic_flow \
  --window-size 2000
```

## Current Implementation Status

Implemented:

- Independent Trident consumer entrypoint.
- Redis Stream input.
- Runtime-only preprocessing.
- Feature matrix construction and column alignment.
- Initial learner creation.
- Window-level batch inference.
- UNKNOWN buffering and DBSCAN clustering.
- `NEW_*` learner creation.
- Incremental learner updates.
- Minimal benchmark output.

Not complete yet:

- Result streams such as `trident:alerts` are not implemented yet.
- Long-running service concerns such as pending-message recovery and graceful
  shutdown need more work.
- The full window engine is still implemented inside
  `pipeline/experiment.py`; it should later move to `runtime/engine.py`.

## Related Code

```text
trident_demo/runtime/online_runner.py
trident_demo/runtime/preprocessing.py
trident_demo/runtime/schema.py
trident_demo/io/redis_loader.py
trident_demo/core/
```
