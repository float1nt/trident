# Directory Organization

This document explains the current `trident_demo/` organization by
responsibility. The code is intentionally not fully moved yet, because existing
imports and CLI profiles still depend on the current package layout.

## Responsibility View

```text
trident_demo/
  services/                 deployment-service responsibility view
    suricata/               Suricata producer contract
    redis/                  Redis stream broker contract
    trident/                Trident online consumer contract

  runtime/                  Trident online runtime code
  io/                       Redis input normalization
  core/                     shared Trident algorithms
  pipeline/                 legacy-compatible experiment pipeline
  orchestration/            demo preflight / inject / data prep
  stress/                   E2E stress harness
  testing/                  test scripts, benchmark guide, generated stress output
  frontend/visualize/       Vite + React frontend dashboard
  benchmark/                timing and resource recorders
  export/                   experiment output and visualization artifacts
  qualification/            learner audit and qualitative metrics
  configs/                  run configs, including online.yaml
```

## Service View

Target online deployment:

```text
Suricata service
  -> Redis service
  -> Trident service
```

Service docs:

```text
services/suricata/README.md
services/redis/README.md
services/trident/README.md
```

## Code View

### Trident Online Runtime

```text
runtime/online_runner.py     online command configuration and runner
runtime/preprocessing.py     runtime-safe preprocessing
runtime/schema.py            runtime feature/schema constants
io/redis_loader.py           Redis Stream/List reader and field normalization
core/                        TSieve / TScissors / TMagnifier
configs/online.yaml          default independent Trident consumer config
```

Command:

```bash
python3 -m trident_demo online --config trident_demo/configs/online.yaml
```

### Experiment Pipeline

```text
pipeline/runner.py           profile orchestration
pipeline/experiment.py       legacy-compatible full experiment pipeline
orchestration/               data prep, Redis inject, preflight, postrun
export/                      full experiment exports
qualification/               audit and qualitative metrics
configs/batch.yaml
configs/replay.yaml
configs/benchmark.yaml
configs/viz_demo.yaml
```

Command:

```bash
python3 -m trident_demo run --profile benchmark
```

### Stress / Test Harness

```text
stress/controller.py         E2E stress coordinator
stress/configs/              stress configs
stress/docker/               tcpreplay image
testing/outputs/stress/      generated stress output
testing/README.md            test responsibility guide
```

Command:

```bash
python3 -m trident_demo.stress trident_demo/stress/configs/e2e.yaml
```

### Visualization Frontend

```text
frontend/visualize/          Vite + React frontend
frontend/visualize/vite.stressDataPlugin.ts
frontend/visualize/src/App.tsx
```

Command:

```bash
cd trident_demo/frontend/visualize
npm run dev
```

## What Was Not Moved

The following directories remain in place for compatibility:

- `pipeline/`
- `stress/`
- `export/`
- `benchmark/`
- `qualification/`
They should not be moved until imports and CLI profiles are migrated. The new
`services/` directory is a deployment responsibility map, not a replacement for
the current Python package layout.

## Next Cleanup Targets

Recommended next moves:

1. Extract a real `runtime/engine.py` for full online window processing.
2. Move experiment-only exports from `pipeline/experiment.py` into an
   `experiment/` package.
3. Move stress result output outside the source tree or add stricter ignore
   rules for `testing/outputs/stress/`.
4. Add production result sinks for `trident:assignments`, `trident:alerts`, and
   `trident:metrics`.
