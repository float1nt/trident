# Scripts

`main.py` is the stable run entrypoint. Research and offline utilities live here.

**学习器定性 / 可视化 artifact 链路**已迁到 [`learner_qualification/`](../learner_qualification/README.md)（统一补导出、拓扑 JSON、指标审计）。本目录下同名文件仅为兼容转发。

## Stable entrypoints

| Task | Command |
| --- | --- |
| Run Trident | `python3 main.py --config configs/config.yaml` |
| Rebuild visualization artifacts for an old run | `python3 learner_qualification/export_visualization_artifacts.py outputs/runs/<run_id>` |
| Viz demo pipeline (aligned data + run) | `bash learner_qualification/run_aligned_viz_pipeline.sh` |

## Script families

The files in this directory are research utilities, not a public Python package.
Use these prefixes to pick the right group:

| Prefix or name | Role |
| --- | --- |
| `prepare_*`, `align_*`, `collect_*`, `clean_*` | Dataset preparation and capture |
| `export_*`, `rebuild_*`, `aggregate_*` | Run artifact export or repair（可视化三类 JSON → `learner_qualification/`） |
| `analyze_*`, `eda_*`, `explore_*`, `explain_*`, `shap_*`, `count_*` | Offline analysis |
| `eval_*`, `run_*_source_test.py` | Evaluation experiments |
| `generate_*`, `run_hpo_*`, `summarize_*` | Sweep and config management |
| `ga_*`, `fit_*` | Feature search and fitting studies |

New workflow scripts should prefer one narrow entrypoint and move reusable logic
into `trident_stream/` modules so one Trident run stays the source of truth for
visualization outputs.
