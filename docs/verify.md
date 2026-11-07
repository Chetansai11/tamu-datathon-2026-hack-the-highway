# Verification record

Verified November 7, 2026. These are local measured results, not a hidden judging score.

| Check | Baseline | Final measured result |
| --- | --- | --- |
| Company graph | No graph | 16 tables, 11 types, 16,979 nodes, 28,190 edges; 814/814 direct-table checks |
| Policy + parser + client + agents + replay integrity | 24 policy tests unavailable before implementation | 80/80 tests pass |
| Actual LLM normalization | 12/15 initially valid | 15/15 after general article/header normalization fixes, same raw model output |
| Public-event independent audit | Do-nothing 3/15 | 15/15 on dry run and clean submission execution |
| Official HTTP calls | 0 calls, incomplete work | 1,120 calls, zero failures |
| Operational outcomes | 0 corrective changes | 50 orders moved, 192 dealer notices, 103 loaners, 3 held lots, 236 stopped VINs, 320 owners contacted |
| Noise / rumor restraint | Noise correct, rumors unhandled | Three noise events make no calls; two rumors only escalate |
| Model usage | No live extraction | Gemini 3.5 Flash-Lite: 12,986 input / 1,306 output tokens, 15 event responses |
| UI | No control tower | 9/9 AppTest scenarios; native graph/action/audit screenshots verified |

The complete event-level comparison and all 15 independently reviewed interpretations are in `docs/evaluation.md`. `runs/submission/audit.json` records every audit result; `action_log.jsonl` is the unmodified official server artifact. `summary.json` records exact source/data hashes and measured execution time. `parsed.json` contains raw actual model output and normalization provenance. The initial invalid text-model catalog choice was rejected before extraction or enterprise writes; the final run selects the actual text model.

Reproduce from the repository root with the shared Python:

```powershell
& 'C:\Users\asus\Desktop\MS\Datathon\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& 'C:\Users\asus\Desktop\MS\Datathon\.venv\Scripts\python.exe' scripts/run.py --provider gemini --out runs/new-dry-run
```

Do not overwrite the submission evidence. After reviewing a fresh extraction, use a new output directory for any clean rerun. Replay reuses actual recorded extraction only after checking event-text hashes. Final score, judging decisions and portal receipt cannot be verified locally. Team eligibility was confirmed; the human must upload before Sunday November 8, 11:30 AM CST.
