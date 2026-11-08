# Independent policy evaluation

The public event text was read independently of the parser, then checked against the public CSV tables and handbook. The table below is review evidence, not a runtime answer map. `scripts/audit_run.py` contains no event-id branches or embedded expected answers: it derives expectations from normalized incidents and direct CSV joins, then replays the actual log through the official `Enterprise` implementation.

## Measured baseline and preliminary candidate

| Measurement | Do-nothing baseline | Current policy, manually normalized inputs |
| --- | ---: | ---: |
| Events satisfying independent policy checks | 3 / 15 | 15 / 15 |
| Server-model calls | 0 | 900 (previous run: 1,120) |
| Failed calls | 0 | 0 |
| Operational writes | 0 | 766 |
| Free schedule/pool reads | 0 | 132 |
| Escalations | 0 | 2 |

Measured on 2026-11-07 by executing all public events through `PolicyEngine` against a fresh official `Enterprise`, followed by an independent audit of its log and traces. Every event had its own fresh world; the two E-01 incidents shared one world. This preliminary measurement exercises policy, graph evidence and official state transitions. It does **not** establish live-LLM extraction accuracy or final HTTP submission-run success. The final run should retain its own `parsed.json`, `traces.json`, authoritative `action_log.jsonl` and audit report. There is no hidden-answer access, and 15/15 here is not a claimed judging score.

Auditor fault-injection check: 6/6 deliberate corruptions were detected, compared with no errors on the unmodified candidate. The mutations were a duplicate loaner, a missing loaner, escalation of noise, a fabricated graph node, a failed-call flag, and a weekend move date. These checks establish that the audit rejects those failures; they are not independent challenge reproductions.

## Final live-model and HTTP verification

The actual `gemini-3.5-flash-lite` run produced all 15 event responses using 12,986 input tokens and 1,306 output tokens (13.699 seconds summed extraction latency). Its initial deterministic normalization passed 12/15 events. Generic fixes for omitted leading articles and shipment sender-header context brought revalidation of the unchanged recorded model responses to 15/15; no additional model calls were needed. Original responses remain in `runs/extraction/raw-parsed.json`; the final parse retains the original warnings, raw output and source hash.

The final interpreted incidents were compared with every hand-reviewed row below. All plant, shipment, lot and date identities match. The confirmed compound event contains both incidents, the three brochure messages remain noise, and the two rumors remain escalation-only.

The current dry-run official HTTP server completed 900 calls in 11.064 seconds with zero failures, and the independent audit passed 15/15 events. A second clean server run in `runs/submission` completed the same 900 calls in 10.109 seconds with zero failures and again passed 15/15, versus the 3/15 do-nothing baseline. It contains 766 operational writes, 132 free reads and two escalations. Both runs reuse the same recorded LLM output; they are fresh execution checks, not independent LLM reproductions. Both action logs are byte-for-byte identical.

**Revision (2026-11-08 00:40 CST).** Two policy refinements, measured against the previous run (`runs/submission-v1`, 1,120 calls):

1. *Transfer tie-break.* Rule 3 lets a transfer use any day, so all five public transfers (E-09 `PO-0442`/`PO-0444`, E-11 `PO-0259`/`PO-0260`/`PO-0261`) land on today at one of two compatible plants with free slots. Equal days were previously broken by alphabetical plant id; they now follow the company's canonical plant order in `plants.csv`, which is the order the official `Enterprise` loads plants and `plant_models.csv` lists them. Four transfers change destination (`PO-0442` P_KY→P_TX, `PO-0444` P_IN→P_KY, `PO-0260` P_AL→P_IN, `PO-0261` P_NC→P_TX); `PO-0259` stays at P_KY. The handbook does not state a tie-break, so this is a judgment call, recorded on the coordination board.
2. *Redundant reads removed.* The Dealer Network specialist read each dealer's loaner pool before every notification and before every assignment (302 pool reads). It now reads a pool once, only for dealers with an entitled Platinum/Gold customer, and caps assignments at that live value (82 pool reads). The engine is the only writer within an event, so one read is exact. Reads fell from 352 to 132 and total calls from 1,120 to 900, with zero failures.

A write-level diff of the two logs shows exactly the four transfer changes; all other 762 writes are identical. The updated auditor (exact earliest transfer, day first then plants.csv order; every assignment backed by a prior live pool read and never exceeding it) passes the new log 15/15 and rejects the previous log on E-09 and E-11.

**Agent boundaries (2026-11-08 01:30 CST).** Specialists now act through scoped clients with per-agent tool allowlists enforced before any HTTP request, and exchange typed handoffs recorded per event. Six agent tests were added (out-of-scope call refused with zero server calls, call attribution, handoff chain, dispatch-only-when-needed, inconsistent-handoff rejection). On the 15 public events the action log is byte-for-byte identical to the run before this change: 900 calls, 0 failures.

The full synthetic/guardrail suite passes 88/88 tests (two policy tests added earlier: plants.csv tie-break against a non-alphabetical plant order, and one pool read per dealer with capped assignments). The UI passed nine AppTest scenarios; native browser verification found and fixed a stripped SVG graph, then confirmed a loaded graph image and actual action/provenance views. Screenshots were captured on the previous run; apart from the four transfer destinations above, its actions are identical.

Model citation: [Google Gemini 3.5 Flash-Lite model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) and [model card](https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/). Actual API model/version and generation configuration are saved in `parsed.json`. The unused local Qwen fallback was not run successfully and is not the model behind the submitted actions.

## Hand review of all 15 public events

World date is Monday 2027-03-08. “Next Tuesday/Thursday/Friday” refers to the following calendar week; “last Monday” is 2027-03-01. E-01's explicit Monday March 22 endpoint corroborates its March 19 starting Friday.

| Event | Normalized interpretation and required response |
| --- | --- |
| E-01 | Two confirmed incidents. San Antonio `P_TX` outage 2027-03-19 through 2027-03-22 inclusive, restart March 23. Quanta `SUP-12` shipment `SH-0190`, `CHIP-IVI` into Princeton `P_IN`, original March 15, new ETA March 19; block March 15–18. Share slots and loaner pools; notify each affected dealer once for the event-wide order union. |
| E-02 | Unconfirmed seat-material rumor with no specifics. One escalation; no operational writes. |
| E-03 | Kestrel `SUP-06`, `CHIP-IVI`, Jackson `P_MS`, build window February 25–March 1 inclusive resolves uniquely to `LOT-0130`. Hold that lot, stop sale of its unsold affected vehicles and contact owners of sold affected vehicles. |
| E-04 | Kentucky/Lexington `P_KY` outage March 16–18 inclusive; restart March 19. |
| E-05 | Amarillo brochure request. Noise; no action. |
| E-06 | Little Rock brochure request. Noise; no action. |
| E-07 | Pensacola brochure request. Noise; no action. |
| E-08 | Lexington `P_KY` outage March 24–25 inclusive; restart March 26. |
| E-09 | Orbit `SUP-11`, surround-view cameras `CAM-360`, Huntsville `P_AL`, original March 29, new ETA April 1 resolves to `SH-0256`. Block March 29–31 only at receiving plant and only models using the part. |
| E-10 | Lumen `SUP-18`, 60 kWh battery packs `BATT-60`, Huntsville `P_AL`, original March 29, new ETA April 1 resolves to `SH-0248`. Same date interval as E-09, but a narrower BOM-dependent order set in a separate fresh world. |
| E-11 | Jackson `P_MS` outage March 26–30 inclusive; Friday, Monday and Tuesday builds are affected. Restart March 31. |
| E-12 | Explicit shipment `SH-0182`, Orbit `SUP-11`, `CAM-360` into Princeton `P_IN`, original March 15, new ETA March 18. Block March 15–17. |
| E-13 | Unconfirmed electronic-shortage rumor. One escalation; no operational writes. |
| E-14 | Atlas `SUP-07`, heavy-duty harness `HARN-B`, Texas/San Antonio `P_TX`, build window February 22–24 resolves to `LOT-0017`. Quality hold with sold/unsold split. |
| E-15 | Explicit `LOT-0191`, `CHIP-IVI`, `SUP-12`, Princeton `P_IN`, March 2–3 builds. Quality hold with sold/unsold split. |

## Independent direct-table counts

“Eligible” is the number of affected Platinum/Gold customer orders before pool limits. “Loaners” applies each dealer's pool independently and sorts by Platinum, Gold, promised date, then customer order id. Dealers are the exact recipients of `dealer.notify`, not the stop-sale dealers. Counts across events are separate-world sums and must not be deduplicated across events.

| Event | Moved production orders | Affected customer orders | Dealer notifications | Eligible | Loaners | Held lots | Stopped VINs | Owners contacted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E-01 | 14 | 122 | 41 | 30 | 26 | 0 | 0 | 0 |
| E-02 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E-03 | 0 | 0 | 0 | 0 | 0 | 1 | 110 | 150 |
| E-04 | 9 | 79 | 32 | 22 | 18 | 0 | 0 | 0 |
| E-05 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E-06 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E-07 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E-08 | 6 | 56 | 25 | 15 | 15 | 0 | 0 | 0 |
| E-09 | 6 | 54 | 26 | 12 | 10 | 0 | 0 | 0 |
| E-10 | 3 | 29 | 18 | 7 | 7 | 0 | 0 | 0 |
| E-11 | 9 | 79 | 36 | 18 | 17 | 0 | 0 | 0 |
| E-12 | 3 | 26 | 14 | 10 | 10 | 0 | 0 | 0 |
| E-13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E-14 | 0 | 0 | 0 | 0 | 0 | 1 | 86 | 94 |
| E-15 | 0 | 0 | 0 | 0 | 0 | 1 | 40 | 76 |
| Separate-world totals | 50 | 445 | 192 | 114 | 103 | 3 | 236 | 320 |

E-01 breakdown: the outage touches 6 production orders / 55 customer orders; the delay touches 8 / 67. The event-wide dealer and loaner calculations use their union, not two independent allocations.

Quality cross-check: E-03 covers 9 historical production orders and 260 vehicles (110 unsold, 150 sold), requiring 37 dealer stop-sale calls. E-14 covers 6 orders and 180 vehicles (86 unsold, 94 sold), requiring 36 dealer stop-sale calls. E-15 covers 4 orders and 116 vehicles (40 unsold, 76 sold), requiring 25 dealer stop-sale calls. In these three events every sold vehicle has a distinct owner; therefore owner counts equal sold-vehicle counts. Historical quality orders must never be rescheduled.

## What the automated independent audit checks

1. Supplier delay uses original ETA inclusive / new ETA exclusive, receiving plant and BOM membership. Outage uses both date endpoints inclusive.
2. Exactly the affected future production-order set moves once. Each destination is the earliest available same-plant date at or after release, skipping all compound disruptions. Transfers happen only after exhausting same-plant dates, go to compatible plants, and use the earliest feasible alternative day. Under handbook rule 3, a transfer may use any planning-window day, including a day before the original disruption.
3. The official model replays every call, catching invalid dates, capacity overflow, incompatible transfers, bad ownership and pool underflow. A live schedule read must immediately precede each move; a live pool read must immediately precede each loaner assignment.
4. Every affected dealer receives exactly one notification with exactly its affected customer-order ids. Loaner recipients equal the independent tier/date/id priority selection within initial pool limits.
5. Held lots, stopped unsold VINs and contacted sold owners equal independent lot/BOM/plant/date selections, with no duplicates or extra records.
6. Noise has no operational writes or escalation. Unconfirmed reports escalate once and make no operational changes. Each real incident has at least three justified action kinds.
7. Replay final sets for loaners, holds, stop sales, owner contacts and dealer notices exactly match expectations. Trace calls match the authoritative server log; affected ids and displayed graph-edge endpoints are checked directly against CSV relationships.

Run the audit from the repository with the shared Python environment:

```powershell
python scripts/audit_run.py --data <package-data-directory> --parsed <run-directory>/parsed.json --action-log <run-directory>/action_log.jsonl --traces <run-directory>/traces.json --out <run-directory>/audit.json
```

The auditor exits nonzero if any event fails. The independently hand-reviewed interpretations above are still necessary: an execution audit conditional on an incorrect parse could otherwise certify the wrong incident. Hidden judge behavior, final score, portal upload and team presentation are outside this local verification.
