# Hack the Highway: Event-Driven Multi-Agent Control Tower — Datathon Submission

## Description

Build a team of AI agents that runs the operations control tower of a just-in-time automaker. Wacky Wheels Co. keeps no parts inventory, so a late shipment, a plant outage or a defective part lot ripples through production schedules, dealers, loaner cars and owners.

The solution is **one coordinating agent plus three specialist agents** (for example Supply Chain Planner, Dealer Network, Customer Care and Quality). It must read a feed of operational events, use an LLM to understand each event, build and traverse an **ontology / knowledge graph** over the company data to find everything the event touches, and then **execute the corrective actions** through the provided enterprise tools, following the policy handbook. It must be robust to messy human wording, multi-incident messages, irrelevant noise and unconfirmed rumors, and it must show a **graph path and reasoning trace** for every event. A business-friendly control-tower view (event feed, graph path, actions taken, audit trail) is expected. Human-in-the-Loop is supported through the `escalate` tool.

Everything runs on a laptop. The company systems are a small local server (`localhost`). No cloud resources are provided or required. Any model or framework may be used, including local small language models.

## Categories

**Event types** the system must tell apart:

* **Supplier Delay:** an inbound shipment of a part will arrive late. Builds that need the part cannot run until the new ETA.
* **Plant Outage:** a plant cannot build for a range of days.
* **Quality Hold:** a lot of a part is defective. The lot must be held, unsold vehicles stopped from sale, and owners of sold vehicles contacted.
* **Noise:** content that has nothing to do with operations. The correct action is no action.
* **Unconfirmed Report:** a vague or unconfirmed rumor. The correct action is `escalate`, with no operational change.
* **Compound:** one message that contains several incidents. Each must be handled, and shared resources (slots, loaner pools) must be used consistently.

**Actions** available through the tools: read schedule, reschedule or transfer a production order, notify a dealer, stop sale of vehicles, check and assign loaners, notify a customer, hold a lot, escalate. Full rules are in `policy_handbook.md`.

## Evaluation Criteria

* **Event understanding:** extract the incident, entities and dates from free text, including nicknames and relative dates ("next Wednesday").
* **Ontology and knowledge graph:** model suppliers, parts, models, plants, production orders, customer orders, customers, dealers, lots, vehicles and shipments, with their relationships, and use it for traversal.
* **Multi-agent orchestration:** a coordinator and three specialist agents with clear responsibilities.
* **Tool execution (MCP-style):** at least three different kinds of action per real incident, following the policy.
* **Precision and guardrails:** no actions on unaffected records, no actions on noise, escalation for unconfirmed reports, graceful handling of failed calls.
* **Explainability:** graph path and reasoning trace per event.
* **Human-in-the-loop:** sensible use of `escalate`.
* **Rich UI:** event feed, graph visualization, action log and audit trail.

## Test Cases (for Judging and Testing)

Use these six test cases to verify end-to-end functioning. All 15 events are in `data/events.json` and are given to you at the start. They are written the way real people write: some clean and structured, some messy, with nicknames and relative dates. The expected answers are not shared; your system must work them out from the event text and the tables.

* **TC1 — Supplier Delay** (3 events)
  Input: a shipment notice, later a chat message ("the Huntsville line is waiting on battery packs…").
  Expected Category: Supplier Delay.
  Judging Focus: resolving the shipment, the affected builds (by bill of materials, at the right plant, in the right date range), dates.
  Expected Outcome:
  * Affected production orders moved to the earliest feasible slot, at the same plant or transferred.
  * One notification to every dealer with an affected customer order, listing only those orders.
  * Loaners for eligible customers, respecting pool limits and priority.
  * Evidence Required: graph path Shipment → Part → Model (BOM) → ProductionOrder → CustomerOrder → Dealer / Customer.

* **TC2 — Plant Outage** (3 events)
  Input: a plant alert with a date range.
  Expected Category: Plant Outage.
  Judging Focus: capacity-aware rescheduling and transfers; every affected order handled, nothing else touched.
  Expected Outcome: orders rescheduled or transferred, dealers notified, loaners assigned.
  Evidence Required: graph path Plant → ProductionOrder → CustomerOrder → Dealer / Customer, and the slot reasoning.

* **TC3 — Quality Hold** (3 events)
  Input: a quality bulletin or chat alert naming a supplier, part, plant and build window.
  Expected Category: Quality Hold.
  Judging Focus: identifying the right lot and the right vehicles; splitting sold and unsold vehicles.
  Expected Outcome: lot held, every unsold affected vehicle stopped from sale at its dealer, every owner of a sold affected vehicle contacted.
  Evidence Required: graph path Lot → ProductionOrder → Vehicle → Dealer / Customer.

* **TC4 — Noise** (3 events)
  Input: a message unrelated to operations (a brochure question, a weather item far away, a price-list notice).
  Expected Category: Noise.
  Judging Focus: restraint.
  Expected Outcome: no write actions.
  Evidence Required: the reason the event was judged not relevant.

* **TC5 — Compound Incident** (1 event)
  Input: a daily digest with two incidents (for example an outage and a supplier delay).
  Expected Category: Plant Outage and Supplier Delay.
  Judging Focus: splitting the message, handling both, and sharing slots and loaner pools without contradictions.
  Expected Outcome: the complete set of actions for both incidents.
  Evidence Required: one graph path per incident.

* **TC6 — Unconfirmed Report** (2 events)
  Input: a rumor with no dates, no details, nothing confirmed.
  Expected Category: Unconfirmed Report.
  Judging Focus: knowing when not to act.
  Expected Outcome: `escalate`, and no write actions.
  Evidence Required: the reason the report was not actionable.

## Scoring and Rubric

* **Event Handling Accuracy (50%):** your action log is replayed on a fresh copy of the world and compared with the expected outcome. Right orders moved, right dealers and customers told, right loaners, right lots and vehicles, noise left alone, unclear reports escalated, and no harmful extra actions.
* **Knowledge Graph and Reasoning (20%):** quality of the ontology, correct traversal, and graph path citations per event.
* **Agent Architecture and Guardrails (10%):** clear agent roles, how the LLM and plain code share the work, validation before acting, handling of failed calls, escalation.
* **Efficiency (10%):** few wasted or failed tool calls, and the use of lightweight or small models that are cheaper yet accurate. Cite the model you used.
* **User Experience and Explainability (10%):** control-tower view, graph and trace visualization, audit-ready summaries.

The top teams are asked to explain their run, and their code is reviewed.

## Submission Notes

* Upload through the portal: `action_log.jsonl` from your run on the 15 events, your source code, an export or diagram of your ontology / graph, and a trace for each event.
* A short end-to-end demo video (or screenshots) showing events arriving, the graph path, the agents acting and the audit trail.
* For every event, the system should provide a summary alongside the reason for what it did or did not do (reasoning module).
* A one-page design card: architecture, LLM versus code, guardrails, evaluation, and what you would improve.
* **Cite the model(s) you used.**

## Package and How to Run

| File | What it is |
|---|---|
| `data/*.csv` | The company: plants, models, parts, bill of materials, suppliers, shipments, production orders, dealers, customers, customer orders, loaners, part lots, finished vehicles, aliases, calendar (about 17,000 records) |
| `data/policy_handbook.md` | The rules your agents must follow. Read this first |
| `data/events.json` | The 15 events to handle |
| `enterprise.py`, `enterprise_server.py` | The mock enterprise systems and a local server for them |

No starter agent, client or solution code is provided.

```
python enterprise_server.py --data data --events data/events.json --out runs/run1 --port 8000
```

* `GET /events` returns the feed. `GET /tools` lists the tools and their arguments.
* `POST /act` with `{"event_id": "...", "tool": "...", "args": {...}}` runs one tool.
* Every call is recorded in `runs/run1/action_log.jsonl`. Each event is handled in its own fresh copy of the world.
* The world restarts empty each time the server starts, so start it once per run. The server refuses to overwrite an existing log unless you pass `--overwrite`.

## Rules

* Teams of 3 to 4. 24 hours.
* Do not hard-code answers or look for hidden files. The system must work from the event text and the tables.
* Submit through the portal. There is no direct contact with the organizers about scoring.
* If a report is not specific or confirmed, escalate. The handbook says exactly when.
# Wacky Wheels Co. Operations Policy Handbook

This is the rulebook your agents must follow. The automated check applies exactly these rules.

## The company in one paragraph

Wacky Wheels Co. builds six models (Pioneer, Summit, Ranger, Nova, Terra, Voyager) in six plants: San Antonio `P_TX`, Lexington `P_KY`, Jackson `P_MS`, Princeton `P_IN`, Huntsville `P_AL` and Greensboro `P_NC`. Plants run lean: **there is no parts inventory**. Each plant builds in daily production orders and has a limited number of build slots per day (`plants.csv`), Monday to Friday. Parts arrive in inbound shipments from about 20 suppliers, and a build can only run once the parts it needs have arrived. Finished vehicles go to about 50 dealers, and many production orders are already promised to customers (customer orders).

Today is Monday 2027-03-08. Working-day index 0 is today. The tables cover the past two weeks (already built) and the next four weeks (the planning window).

## Events

An event is a short message (email, plant alert, quality bulletin, chat, news wire). Each one is one of:

| Kind | What it means |
|---|---|
| Supplier delay | An inbound shipment of a part will arrive later than planned. |
| Plant outage | A plant cannot build for a range of days. |
| Quality hold | A lot of a part is defective. |
| Noise | Not about our operations. |
| Unconfirmed rumor | Possibly about us, but not confirmed or specific. |

Some messages combine several incidents. Every event is handled in its own copy of the world, so nothing you do for one event affects another.

## Rules

1. **Supplier delay.** Builds that need the delayed part cannot run from the original ETA up to (but not including) the new ETA. Those production orders are affected. A production order needs a part if its model's bill of materials (`bom.csv`) includes it, and only at the receiving plant.
2. **Plant outage.** No builds at the plant during the outage (inclusive). Every production order of that plant in the outage is affected, and the plant restarts the next working day.
3. **Rescheduling.** Move each affected production order to the earliest feasible slot. At the same plant the new day must be at or after the end of the disruption (the new ETA, or the day after the outage), and a day only has a limited number of slots (`slots_per_day`). If no same-plant slot is free, transfer the order to another plant that builds the model (`plant_models.csv`) on any day with a free slot. Never move orders that are not affected.
4. **Dealer notification.** Every dealer with at least one affected customer order gets exactly one `dealer.notify` listing those customer order ids, and only those.
5. **Loaners.** For affected customer orders, a customer in tier Platinum or Gold gets one loaner from their dealer's pool. Pools are limited (`crm.loaner_availability`). When there are more entitled customers than loaners, the priority is Platinum before Gold, then the earlier promised date, then the lower customer order id. Standard customers get no loaner (the dealer is told, nothing else).
6. **Quality hold.** Hold the lot (`quality.hold_lot`). The affected vehicles are the finished vehicles built at that plant, on the lot's build dates, from production orders of models that use the part. Unsold vehicles (`in_stock`) are stopped from sale at their dealer (`dealer.stop_sale`). For sold vehicles, contact the owner (`crm.notify_customer`).
7. **Noise.** Do nothing operational. Do not call any write tool.
8. **Unconfirmed or unclear.** Do not take any operational action. Use `escalate`.
9. **Completeness.** A real incident should end with at least three different kinds of action (for example reschedule, notify dealers, assign loaners).
10. **Do not touch what is not affected.** Wrong or extra actions are penalized.

## Tools

`GET /tools` lists them. Every call is `POST /act` with `{"event_id", "tool", "args"}`. Failed calls change nothing but are logged and counted. Read tools (`mes.get_schedule`, `crm.loaner_availability`) are free and never penalized.

## Dates

Dates in events are sometimes written relative to today ("next Wednesday", "last Thursday"). Today is Monday 2027-03-08. Tool dates are always `YYYY-MM-DD`, weekdays only, from today through 2027-04-02.

## Names

People write names in many ways ("the Texas plant", "heavy-duty wiring harness", "Volt"). `aliases.csv` lists the known variants. Resolve names to ids before you act.
