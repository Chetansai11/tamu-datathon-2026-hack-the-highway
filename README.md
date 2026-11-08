# Wacky Wheels Control Tower

TAMU Datathon 2026 · Challenge 6, Hitachi: Hack the Highway.

One coordinator and three bounded specialists handle supplier delays, plant outages, quality holds, noise and rumors. A small LLM extracts grounded incident facts. A typed NetworkX graph identifies the affected entities; plain Python executes handbook rules. Every event uses its own fresh official enterprise world, with shared slots and loaner pools inside compound events.

## Run locally

Use the existing shared environment. The examples below run from this repository's root. Official CSVs remain in `data/package/hack_the_highway_package/data`; the worktree runner also finds the main checkout automatically. See [starter setup](docs/SETUP.md) to obtain the public package after cloning.

```powershell
$py = 'C:\Users\asus\Desktop\MS\Datathon\.venv\Scripts\python.exe'
& $py -m unittest discover -s tests -v
& $py scripts/run.py --provider gemini --out runs/dry-run
& $py scripts/run.py --parsed-file runs/dry-run/parsed.json --out runs/submission
& $py scripts/package_submission.py
& $py -m streamlit run src/app.py --server.address 127.0.0.1 --server.port 8506 --server.headless true
```

Configure `GEMINI_API_KEY` in the shared Datathon `.env`, read only through `toolkit/prize_apis.py`. Keys are never included in the package or logs. The Gemini adapter lists available models and selects a supported Flash Lite model; `--model-name` can select a catalog-verified alternative. The actual model and returned version are recorded with each event. An optional local Qwen2.5 1.5B backend is available via `--provider local --model <directory>`; its weights must be downloaded separately with `scripts/fetch_model.py`.

The first run calls the LLM once per event and preserves raw output, text hashes, normalized incidents and usage. Review all extracted incidents against [the independent event interpretation](docs/evaluation.md). The second run reuses that recorded LLM evidence only when all event-text hashes match, then starts one clean official server and produces the submission log. This avoids another nondeterministic extraction or extra API consumption. Choose a new output directory to preserve an earlier run. `--overwrite` is explicit and intended for disposable development runs only.

The runner starts and stops the official server on port 8606 within one process lifetime. The UI uses 8506 and reads completed artifacts; it does not issue enterprise writes. Set `HIGHWAY_RUN_DIR` to inspect a different run.

## Evidence and guardrails

- `runs/<run>/action_log.jsonl`: authoritative, unmodified official server log.
- `parsed.json`: actual model output, normalized incidents, model/version and usage.
- `traces.json`: graph paths, bounded specialist decisions, reads and writes.
- `audit.json`: independent CSV expectations and official replay, with do-nothing baseline.
- `summary.json`: measured execution, source/data hashes and model usage.
- `outputs/ontology/`: complete graph JSON, GraphML, Mermaid diagram and source provenance.
- `outputs/submission/hitachi-control-tower-submission.zip`: audited artifacts and an explicit source allowlist, with SHA-256 manifest.

Each agent acts through a scoped client with its own tool allowlist; an out-of-scope call is refused before any HTTP request. Agents pass typed handoffs (recorded in `traces.json` and shown in the UI's "Agents & handoffs" tab). Dates and aliases are resolved in code. Unknown or contradictory facts fail closed. Only affected entities may be changed. Before moves and loaners the client reads live capacity. Dealer notifications and loaner priorities are computed across the whole event. Uncertain write outcomes stop execution and are never retried automatically. The package builder rejects failed/incomplete audits and source changes after the verified run.

The public-data audit is not the hidden judging score. Team eligibility was confirmed by the human; portal upload, repository push and publication remain human actions. Feature freeze: Sunday November 8, 8:00 AM CST; submit by 11:30 AM CST.

See [handbook and brief](docs/rules.md), [tool contract](docs/tools.md), and [independent evaluation](docs/evaluation.md).
