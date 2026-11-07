# Enterprise tool contract

Fetched from the official local server's `GET /tools`.

Every call: `POST /act` with `event_id`, `tool`, and `args`.
Each event has an independent fresh world. Compound incidents share that event's world.

| Tool | Arguments | Behavior |
| --- | --- | --- |
| `mes.get_schedule` | `plant_id: str`; `date: YYYY-MM-DD` | Orders built at a plant on a date, with free slots (live view). |
| `mes.reschedule` | `production_order_id: str`; `new_date: YYYY-MM-DD` | Move a future production order to another working day at the same plant. |
| `mes.transfer` | `production_order_id: str`; `to_plant_id: str`; `new_date: YYYY-MM-DD` | Move a future production order to another plant that builds the model. |
| `dealer.notify` | `dealer_id: str`; `customer_order_ids: list[str]`; `message: str` | Tell a dealer about delayed customer orders. |
| `dealer.stop_sale` | `dealer_id: str`; `vins: list[str]` | Stop sale of unsold vehicles (by VIN) at a dealer. |
| `crm.loaner_availability` | `dealer_id: str` | Loaner cars still free at a dealer. |
| `crm.assign_loaner` | `customer_order_id: str` | Give the customer of a delayed order a loaner car from their dealer's pool. |
| `crm.notify_customer` | `customer_id: str`; `message: str` | Contact a customer (owner or buyer). |
| `quality.hold_lot` | `lot_id: str` | Place a part lot on quality hold. |
| `escalate` | `reason: str` | Hand an unclear or unconfirmed report to a human. |

## Client safeguards

`EnterpriseClient` accepts only a local HTTP origin, known event ids and tool names, exact argument keys, nonempty strings and lists, and unique list entries. Tool dates must be canonical ISO weekdays from 2027-03-08 through 2027-04-02.

Only `mes.get_schedule` and `crm.loaner_availability` may retry automatically. Operational writes and `escalate` are never retried. A connection failure or malformed response after a write raises `UnknownOutcomeError`; inspect the authoritative server log before restarting. HTTP 4xx tool rejection raises `ToolCallError`.

Client validation does not decide operational policy. The policy layer must read schedules/pools before writes and validate affected entities against the graph and tables. `escalate` is classified as non-operational by the official server but still changes escalation state.

The official `runs/<run>/action_log.jsonl` is the submission log. The optional client audit log also records responses, locally rejected requests, timings and unknown outcomes; it is separate from the official log.
