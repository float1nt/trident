# Runtime Attack Taxonomy Implementation Plan

**Goal:** Replace legacy runtime attack-family labels with the confirmed table taxonomy, attach a top-level category to each result, and fix benign fallback classification for CIC bidirectional flows.

**Architecture:** Keep the existing learner-level audit pipeline. Update `quality.py` so rule matching emits only the confirmed taxonomy and computes reciprocity from CIC forward/backward packet counts when available. Update the API display dictionary and tests to consume the new labels and categories.

**Tech Stack:** Python, pytest, learner topology metrics, CICFlowMeter-style flow records.

---

### Task 1: Lock the new rule contract with tests

- [ ] Add tests for the five supported attack labels and `attack_category`.
- [ ] Add a regression test proving balanced CIC flows can fall back to `BENIGN_NORMAL`.
- [ ] Run the targeted tests and confirm they fail before implementation.

### Task 2: Fix realtime reciprocity and replace legacy rules

- [ ] Compute learner reciprocity from `Total Fwd Packet` and `Total Bwd packets` when available.
- [ ] Remove legacy DoS/DDoS family outputs.
- [ ] Emit only the five confirmed attack labels plus benign and unnamed fallbacks.
- [ ] Attach `attack_category` to attack results and rule hits.

### Task 3: Update API display metadata

- [ ] Replace the old attack dictionary with the five confirmed labels.
- [ ] Expose the original-table category names in API attack-type metadata.
- [ ] Update page query fixtures and assertions.

### Task 4: Verify

- [ ] Run targeted runtime quality tests.
- [ ] Run the full analysis backend pytest suite.
- [ ] Search the runtime backend for deleted attack-family labels.
