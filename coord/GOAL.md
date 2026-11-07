# Hitachi: Hack the Highway

- **Goal:** A control tower for Wacky Wheels Co. (just-in-time automaker, no parts inventory): 1 coordinator agent + 3 specialist agents read 15 free-text events, use an LLM to understand each, traverse a knowledge graph over the company tables, and execute the corrective tools on the local enterprise server, following `policy_handbook.md` exactly.
- **Scored by:** Event Handling Accuracy 50% (our `action_log.jsonl` is replayed on a fresh world and compared with the hidden expected outcome: right orders moved, right dealers/customers told, right loaners, right lots/vehicles, noise untouched, rumors escalated, extra actions penalized). Knowledge Graph and Reasoning 20% (ontology, traversal, a graph path cited per event). Agent Architecture and Guardrails 10%. Efficiency 10% (few wasted or failed calls, small/cheap model, cite it). UX and Explainability 10% (event feed, graph view, action log, audit trail). Top teams explain their run and have code reviewed.
- **Submit:** Through the portal: `action_log.jsonl` from the run on all 15 events, source code, ontology/graph export or diagram, a trace per event (summary + reason for what it did or did not do), a short demo video or screenshots, a one-page design card (architecture, LLM vs code, guardrails, evaluation, improvements), and the model(s) cited.
- **Rules and limits:** Teams of 3 to 4 (stated in the brief). Do not hard-code answers or look for hidden files; the system must work from event text and tables. No direct contact with organizers about scoring. Policy rules 1-10 in `data/package/hack_the_highway_package/data/policy_handbook.md` are what the automated check applies. Today in the world is Mon 2027-03-08; tool dates are weekdays 2027-03-08 to 2027-04-02. Read tools are free; failed write calls are logged and counted. The server's world resets on each start and refuses to overwrite a log without `--overwrite`.
- **Definition of done:** One clean server run over all 15 events producing `action_log.jsonl`, with per-event traces and graph paths, the UI, the design card and the demo submitted.
- **Deadline:** Sun Nov 8. Hacking ends 12:00 PM, submit by 11:30 AM. Feature freeze 8:00 AM.
- **Prizes:** 1st $50, 2nd $30, 3rd $20 Amazon gift cards
- **Guide:** `data/package/hack_the_highway_package/Usecase.md` (same text as the .docx). Package: https://tamudatathon.com/downloads/hack_the_highway_student_package.zip
- **Suggested repo name:** tamu-hack-the-highway

**Approach note:** 50% is deterministic policy execution, so the LLM should only extract structured incidents (type, entities, dates, confirmed or not) and plain code should do the graph traversal, slot search and loaner priority. That is also what Efficiency rewards.

Source: the starter package brief and policy handbook, read Sat Nov 7. The challenge's own rules override everything else.
