# Proofcheck Documentation

Use this trigger phrase in a new conversation:

`proofcheck documentation`

When asked, the assistant should run this checklist and report pass/fail with gaps:

1. Confirm core docs exist and are current:
   - `knowledge/home_server_pipeline.md`
   - `knowledge/rules.md`
   - `knowledge/go_live.md`
   - `knowledge/changelog.md`
2. Confirm server pipeline files exist:
   - `scripts/home_server/run_nightly.sh`
   - `scripts/home_server/fetch_runs.sh`
   - `scripts/home_server/make_manifest.py`
   - `scripts/home_server/prune_runs.py`
   - `scripts/home_server/systemd/cdx-trade-nightly.service`
   - `scripts/home_server/systemd/cdx-trade-nightly.timer`
3. Confirm pull metadata exists and is readable:
   - `data/server_runs_remote/_meta/pull_history.tsv`
4. Confirm latest pulled run exists and has `manifest.json`.
5. Print a concise summary:
   - latest run id
   - constrained / constrained_capacity3 / unconstrained stats
   - current known bottleneck (`no_slot`, `risk_cap`, or other)
6. List missing/stale items and exact fixes.
7. Run `uv run python main.py analyze-latest-run --root data/server_runs_remote` and include output in the proofcheck summary.

## Copy/Paste Prompt

Use this exact prompt in future chats:

`proofcheck documentation: run the repository checklist in knowledge/proofcheck_documentation.md, verify all files and latest run metadata, summarize pass/fail, and propose exact fixes for anything missing or stale.`
