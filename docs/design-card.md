# Highway Control Tower - design card

TAMU Datathon 2026, Challenge 6: Hitachi Hack the Highway. A local control tower turns free-text disruptions into traceable enterprise actions for Wacky Wheels Co.

## Architecture

Event text -> Gemini extraction -> grounded coordinator -> three bounded specialists -> validated official HTTP tools. The Supply Chain Planner finds affected builds and earliest feasible slots or compatible transfers. Dealer Network / Customer Care unions affected orders, notifies each dealer once, and allocates loaners by tier, promised date and order ID. Quality holds lots, stops sale of unsold vehicles and contacts sold-vehicle owners. Every event gets a fresh world; compound incidents share slots and pools.

## LLM versus deterministic code

The LLM classifies and splits messages, extracting entity references, confirmation and date phrases. Code resolves aliases and relative dates, traverses the BOM and knowledge graph, selects affected records and decides all actions. Raw model output and normalization provenance remain available. The final execution reuses the same recorded raw extraction after generic normalization fixes; it is not an independent model reproduction.

## Guardrails

Read live schedules and loaner pools before writes. Validate exact tool arguments, identifiers, dates and affected scope. Never automatically retry a write with uncertain outcome. Noise makes no calls; unconfirmed reports only escalate. Preserve per-event graph paths, reasons, tool responses and the official action log. No event-id answer branches.

## Measured evidence

| Measure | Baseline | Recorded result |
| --- | --- | --- |
| Independent public-event audit | Do nothing: 3/15 | 15/15 |
| Tests | No implemented policy/parser/client/agents | 80/80 |
| Graph | No graph | 16 tables, 11 types, 16,979 nodes, 28,190 edges; 814/814 direct-table checks |
| Official server calls | Zero calls, incomplete corrective work | 1,120 calls, 0 failures |
| Actions | Zero corrective writes | 766 writes + 352 free reads + 2 escalations |

Final HTTP execution took 9.086 seconds; the dry run took 16.760 seconds. These are observed run durations, not a comparative benchmark. The dry-run and final action logs are byte-for-byte identical.

## Model citation and efficiency

Actual model: **gemini-3.5-flash-lite**, [Google Gemini 3.5 Flash-Lite documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite). Fifteen event responses used **12,986 input tokens** and **1,306 output tokens**. The model extracts; deterministic specialists decide and act. No extra LLM calls were required for normalization fixes or clean execution replay.

## Limits and next improvements

The local audit is not a hidden judging score. Portal upload remains human-only. Next improvements: calibrated uncertainty and more paraphrase holdouts. Demo screenshots show the actual dry run, whose actions match the clean final run.

- [One-page PDF](design-card.pdf)
- [Rendered design card](design-card.png)
- [Full ontology](ontology.svg)
- [Control-tower overview](demo-overview.jpg)
- [Actual shipment graph path](demo-shipment-graph.jpg)
- [Action audit and recorded responses](demo-action-audit.jpg)
