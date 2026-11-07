# Hitachi starter setup

Verified on November 7, 2026 against the starter archive already downloaded into this repository.

- Official challenge: https://tamudatathon.com/challenges/6
- Official package: https://tamudatathon.com/downloads/hack_the_highway_student_package.zip
- Original archive: `data/package.zip` (ignored by Git).
- Original extracted package: `data/package/hack_the_highway_package/` (ignored by Git).
- Versioned starter: `starter/enterprise.py`, `starter/enterprise_server.py`, and `starter/Usecase.md`, copied without changes from the supplied package.
- Source and integrity record: [starter-manifest.json](starter-manifest.json).

The repository is independent of the other challenges. Keep solution code in `src/`, experiments in `runs/`, and generated results in `outputs/`. The existing task ownership decisions remain in effect; run `coord.py brief` before claiming work.

## Run the official enterprise server

From this challenge's repository root in PowerShell:

```powershell
& ..\..\.venv\Scripts\python.exe -B starter/enterprise_server.py --data data/package/hack_the_highway_package/data --events data/package/hack_the_highway_package/data/events.json --out runs/enterprise-dev --port 8606
```

The server binds to `127.0.0.1`. Port **8606** is reserved for this challenge's enterprise server. It exposes `GET /events`, `GET /tools`, and `POST /act`; use a different port if a future UI runs alongside it. Each start creates a fresh world. Use a new `--out` folder for a new experiment; preserve action logs needed for comparison or submission. The supplied server refuses to overwrite a nonempty log unless explicitly asked.

The official starter uses the Python standard library. No dependency installation is needed to run that server. Use the existing shared Python environment; do not change its packages without a coordination decision.

## Recreate data after cloning

Challenge data and the archive are deliberately ignored by Git. On a new checkout, download the official package into `data/package.zip`, verify SHA256 `6573a2c19093a0957cf20e85febb87a446048de2bf3a40972b1202ad2a1c71df`, and extract it into `data/package/`. The data path in the command must then contain `events.json`, `policy_handbook.md`, and the 16 CSV tables. If the organizer updates the package, record the new version and inspect the changes before replacing existing files.

## Checks performed

| Check | Result |
|---|---|
| Existing archive integrity | Passed ZIP CRC validation |
| Extracted package | All 22 files match the archive byte for byte |
| Versioned starter files | All three files match the supplied extracted package |
| Python syntax | Both official Python files parse |
| Enterprise data loading | Passed across 16 CSV tables |
| Event feed | 15 events, 15 unique event IDs |
| Tool registry | 10 tools |
| Read operation | In-memory `mes.get_schedule` returned a valid schedule |

These checks establish starter readiness. The HTTP server has not been smoke-tested, and no solution, LLM call, corrective-action run, or submission has been validated. See [rules.md](rules.md) and `coord/GOAL.md` for the challenge requirements.
