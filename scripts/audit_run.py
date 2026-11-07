"""Independent, direct-CSV policy audit plus replay through the official server model.

No event answers are embedded here. Expected records are selected from normalized
incidents and the public tables without importing the runtime policy or graph.
This validates execution conditional on parsing; the human event review remains
separate evidence for whether the normalized incidents match the source text.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

READS = {"mes.get_schedule", "crm.loaner_availability"}
FIRST = date(2027, 3, 8)
LAST = date(2027, 4, 2)
RANK = {"Platinum": 0, "Gold": 1}


def load_json(path):
    p = Path(path)
    if p.suffix == ".jsonl":
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(p.read_text(encoding="utf-8"))


def records_by_event(records):
    if isinstance(records, dict):
        if "events" in records:
            records = records["events"]
        elif "traces" in records:
            records = records["traces"]
        else:
            return records
    return {row["event_id"]: row for row in records}


def working_days(start=FIRST):
    current = max(FIRST, start)
    while current <= LAST:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def _official(data_dir):
    source = Path(data_dir).parent / "enterprise.py"
    if not source.is_file():
        raise ValueError(f"Official enterprise.py missing beside data: {source}")
    spec = importlib.util.spec_from_file_location("audit_official_enterprise", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IndependentAudit:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.tables = {p.stem: list(csv.DictReader(p.open(encoding="utf-8", newline="")))
                       for p in self.data_dir.glob("*.csv")}
        t = self.tables
        self.po = {r["production_order_id"]: r for r in t["production_orders"]}
        self.co = {r["customer_order_id"]: r for r in t["customer_orders"]}
        self.customers = {r["customer_id"]: r for r in t["customers"]}
        self.shipments = {r["shipment_id"]: r for r in t["inbound_shipments"]}
        self.lots = {r["lot_id"]: r for r in t["part_lots"]}
        self.vehicles = {r["vin"]: r for r in t["finished_vehicles"]}
        self.pools = {r["dealer_id"]: int(r["loaners_available"]) for r in t["loaners"]}
        self.models = defaultdict(set)
        self.parts = defaultdict(set)
        for row in t["plant_models"]:
            self.models[row["plant_id"]].add(row["model"])
        for row in t["bom"]:
            self.parts[row["model"]].add(row["part_id"])
        self.official = _official(data_dir)

    def expectation(self, incidents):
        details, affected, lots, stopped, owners = [], set(), set(), set(), set()
        for incident in incidents:
            kind = incident["kind"]
            item = {"kind": kind, "po": set(), "co": set(), "lots": set(), "stopped": set(), "owners": set()}
            if kind not in {"noise", "unconfirmed"} and incident.get("confirmed") is not True:
                raise ValueError(f"Real incident is not explicitly confirmed: {kind}")
            if kind == "supplier_delay":
                shipment = self.shipments[incident["shipment_id"]]
                start, end = shipment["eta_date"], incident["new_eta"]
                if end <= start:
                    raise ValueError("Supplier delay new ETA must follow original ETA")
                item.update(plant=shipment["plant_id"], part=shipment["part_id"], start=start, end=end,
                            release=date.fromisoformat(end), shipment_id=shipment["shipment_id"])
                item["po"] = {pid for pid, p in self.po.items() if p["plant_id"] == item["plant"]
                              and item["part"] in self.parts[p["model"]]
                              and start <= p["build_date"] < end and p["build_date"] >= FIRST.isoformat()}
            elif kind == "plant_outage":
                start, end = incident["start_date"], incident["end_date"]
                if end < start:
                    raise ValueError("Outage end must not precede its start")
                item.update(plant=incident["plant_id"], start=start, end=end,
                            release=date.fromisoformat(end) + timedelta(days=1))
                item["po"] = {pid for pid, p in self.po.items() if p["plant_id"] == item["plant"]
                              and start <= p["build_date"] <= end and p["build_date"] >= FIRST.isoformat()}
            elif kind == "quality_hold":
                lot = self.lots[incident["lot_id"]]
                item["lots"].add(lot["lot_id"])
                item.update(plant=lot["plant_id"], part=lot["part_id"],
                            start=lot["first_build_date"], end=lot["last_build_date"])
                item["po"] = {pid for pid, p in self.po.items() if p["plant_id"] == item["plant"]
                              and item["part"] in self.parts[p["model"]]
                              and item["start"] <= p["build_date"] <= item["end"]}
                for vin, vehicle in self.vehicles.items():
                    if vehicle["production_order_id"] in item["po"]:
                        if vehicle["status"] == "in_stock":
                            item["stopped"].add(vin)
                        elif vehicle["status"] == "sold":
                            item["owners"].add(vehicle["customer_id"])
                lots |= item["lots"]
                stopped |= item["stopped"]
                owners |= item["owners"]
            elif kind not in {"noise", "unconfirmed"}:
                raise ValueError(f"Unknown incident kind: {kind}")
            if kind in {"supplier_delay", "plant_outage"}:
                affected |= item["po"]
                item["co"] = {cid for cid, c in self.co.items() if c["production_order_id"] in item["po"]}
            details.append(item)
        cos = {cid for cid, c in self.co.items() if c["production_order_id"] in affected}
        dealers = defaultdict(set)
        eligible = defaultdict(list)
        for cid in cos:
            c = self.co[cid]
            dealers[c["dealer_id"]].add(cid)
            if self.customers[c["customer_id"]]["tier"] in RANK:
                eligible[c["dealer_id"]].append(cid)
        loaners = set()
        for dealer, candidates in eligible.items():
            candidates.sort(key=lambda cid: (RANK[self.customers[self.co[cid]["customer_id"]]["tier"]],
                                             self.co[cid]["promised_date"], cid))
            loaners.update(candidates[:self.pools[dealer]])
        return {"details": details, "affected": affected, "cos": cos, "dealers": dict(dealers),
                "eligible": dict(eligible), "loaners": loaners, "lots": lots, "stopped": stopped,
                "owners": owners, "escalate": any(d["kind"] == "unconfirmed" for d in details)}

    @staticmethod
    def blocked(plant, model, day, details, parts):
        value = day.isoformat()
        for d in details:
            if d.get("plant") != plant:
                continue
            if d["kind"] == "plant_outage" and d["start"] <= value <= d["end"]:
                return True
            if d["kind"] == "supplier_delay" and d["part"] in parts[model] and d["start"] <= value < d["end"]:
                return True
        return False

    def valid_path(self, path):
        """Validate displayed edge endpoints directly against table foreign keys."""
        nodes, edges = path.get("nodes", []), path.get("edges", [])
        if len(nodes) < 2 or len(edges) != len(nodes) - 1:
            return False
        for source, target, edge in zip(nodes, nodes[1:], edges):
            if edge.get("source") != source or edge.get("target") != target:
                return False
            try:
                sk, si = source.split(":", 1)
                tk, ti = target.split(":", 1)
                pair = (sk, tk)
                valid = False
                if pair == ("Shipment", "Part"):
                    valid = self.shipments[si]["part_id"] == ti
                elif pair == ("Part", "Model"):
                    valid = si in self.parts[ti]
                elif pair == ("Model", "ProductionOrder"):
                    valid = self.po[ti]["model"] == si
                elif pair == ("Plant", "ProductionOrder"):
                    valid = self.po[ti]["plant_id"] == si
                elif pair == ("ProductionOrder", "CustomerOrder"):
                    valid = self.co[ti]["production_order_id"] == si
                elif pair == ("CustomerOrder", "Dealer"):
                    valid = self.co[si]["dealer_id"] == ti
                elif pair == ("CustomerOrder", "Customer"):
                    valid = self.co[si]["customer_id"] == ti
                elif pair == ("Lot", "ProductionOrder"):
                    lot, po = self.lots[si], self.po[ti]
                    valid = (po["plant_id"] == lot["plant_id"] and lot["part_id"] in self.parts[po["model"]]
                             and lot["first_build_date"] <= po["build_date"] <= lot["last_build_date"])
                elif pair == ("ProductionOrder", "Vehicle"):
                    valid = self.vehicles[ti]["production_order_id"] == si
                elif pair == ("Vehicle", "Dealer"):
                    valid = self.vehicles[si]["dealer_id"] == ti
                elif pair == ("Vehicle", "Customer"):
                    valid = self.vehicles[si]["customer_id"] == ti
                if not valid:
                    return False
            except (ValueError, KeyError):
                return False
        return True

    def audit(self, parsed, action_rows, traces=None):
        parsed = records_by_event(parsed)
        trace_map = records_by_event(traces) if traces is not None else None
        public_events = load_json(self.data_dir / "events.json")
        known = {e["event_id"] for e in public_events}
        overall_errors = [f"Unknown event in parsed input: {eid}" for eid in parsed if eid not in known]
        by_event = defaultdict(list)
        for row in action_rows:
            by_event[row.get("event_id")].append(row)
            if row.get("event_id") not in known:
                overall_errors.append(f"Unknown event in action log: {row.get('event_id')}")
        enterprise = self.official.Enterprise(str(self.data_dir))
        summaries = []
        for event in public_events:
            eid = event["event_id"]
            errors, rows = [], by_event[eid]
            if eid not in parsed:
                summaries.append({"event_id": eid, "passed": False, "errors": ["Missing parsed event"], "baseline_passed": False})
                continue
            try:
                incidents = parsed[eid]["incidents"]
                if not incidents:
                    raise ValueError("Empty incidents list")
                expected = self.expectation(incidents)
            except (KeyError, ValueError, TypeError) as exc:
                summaries.append({"event_id": eid, "passed": False, "errors": [f"Invalid normalized incident: {exc}"], "baseline_passed": False})
                continue
            moves, notified, assigned, held, stopped, contacted = [], defaultdict(list), [], [], [], []
            actions_per_incident = [set() for _ in incidents]
            escalations = 0
            state = enterprise.state(eid)
            for number, row in enumerate(rows, 1):
                tool, args = row.get("tool"), row.get("args", {})
                if row.get("ok") is not True:
                    errors.append(f"Call {number} is logged as failed")
                if tool in {"mes.reschedule", "mes.transfer"}:
                    pid = args.get("production_order_id")
                    moves.append(pid)
                    if pid not in expected["affected"]:
                        errors.append(f"Moved unaffected production order {pid}")
                    elif pid in state["loc"]:
                        original = self.po[pid]
                        plant = original["plant_id"]
                        relevant = [d for d in expected["details"] if pid in d["po"] and d["kind"] in {"supplier_delay", "plant_outage"}]
                        release = max(d["release"] for d in relevant)
                        def free(target, day):
                            idx = self.official.date_to_idx(day)
                            return (len(state["slots"][(target, idx)]) < enterprise.plants[target]["slots"]
                                    and not self.blocked(target, original["model"], day, expected["details"], self.parts))
                        same = [d for d in working_days(release) if free(plant, d)]
                        target = plant if tool == "mes.reschedule" else args.get("to_plant_id")
                        day = args.get("new_date")
                        if same:
                            if tool != "mes.reschedule" or day != same[0].isoformat():
                                errors.append(f"{pid}: expected earliest same-plant slot {plant}/{same[0]}, got {target}/{day}")
                        else:
                            alternatives = [(d, other) for d in working_days() for other in sorted(self.models)
                                            if other != plant and original["model"] in self.models[other] and free(other, d)]
                            if not alternatives:
                                errors.append(f"{pid}: no feasible slot exists")
                            elif tool != "mes.transfer" or (day, target) not in {(d.isoformat(), p) for d, p in alternatives} or day != alternatives[0][0].isoformat():
                                errors.append(f"{pid}: transfer is not an earliest feasible alternative")
                        prior = rows[number - 2] if number > 1 else {}
                        if (prior.get("tool") != "mes.get_schedule"
                                or prior.get("args") != {"plant_id": target, "date": day}):
                            errors.append(f"{pid}: no immediate destination schedule read before move")
                    for index, detail in enumerate(expected["details"]):
                        if pid in detail["po"]:
                            actions_per_incident[index].add(tool)
                elif tool == "dealer.notify":
                    notified[args.get("dealer_id")].append(args.get("customer_order_ids", []))
                    for index, detail in enumerate(expected["details"]):
                        if set(args.get("customer_order_ids", [])) & detail["co"]:
                            actions_per_incident[index].add(tool)
                elif tool == "crm.assign_loaner":
                    assigned.append(args.get("customer_order_id"))
                    cid = args.get("customer_order_id")
                    prior = rows[number - 2] if number > 1 else {}
                    if (cid in self.co and (prior.get("tool") != "crm.loaner_availability"
                            or prior.get("args") != {"dealer_id": self.co[cid]["dealer_id"]})):
                        errors.append(f"{cid}: no immediate pool read before loaner assignment")
                    for index, detail in enumerate(expected["details"]):
                        if args.get("customer_order_id") in detail["co"]:
                            actions_per_incident[index].add(tool)
                elif tool == "quality.hold_lot":
                    held.append(args.get("lot_id"))
                    for index, detail in enumerate(expected["details"]):
                        if args.get("lot_id") in detail["lots"]:
                            actions_per_incident[index].add(tool)
                elif tool == "dealer.stop_sale":
                    stopped.extend(args.get("vins", []))
                    for index, detail in enumerate(expected["details"]):
                        if set(args.get("vins", [])) & detail["stopped"]:
                            actions_per_incident[index].add(tool)
                elif tool == "crm.notify_customer":
                    contacted.append(args.get("customer_id"))
                    for index, detail in enumerate(expected["details"]):
                        if args.get("customer_id") in detail["owners"]:
                            actions_per_incident[index].add(tool)
                elif tool == "escalate":
                    escalations += 1
                elif tool not in READS:
                    errors.append(f"Unexpected tool {tool}")
                try:
                    enterprise.call(eid, tool, args)
                except Exception as exc:
                    errors.append(f"Official replay rejected call {number}: {type(exc).__name__}: {exc}")
            def exact(label, observed, wanted):
                actual = set(observed)
                missing, extra = wanted - actual, actual - wanted
                if missing or extra:
                    errors.append(f"{label}: missing={len(missing)} extra={len(extra)}; examples missing={sorted(missing)[:3]} extra={sorted(extra)[:3]}")
                duplicates = [key for key, count in Counter(observed).items() if count > 1]
                if duplicates:
                    errors.append(f"{label}: duplicate ids {duplicates[:3]}")
            exact("moved orders", moves, expected["affected"])
            exact("loaner orders", assigned, expected["loaners"])
            exact("held lots", held, expected["lots"])
            exact("stopped vehicles", stopped, expected["stopped"])
            exact("contacted owners", contacted, expected["owners"])
            if set(notified) != set(expected["dealers"]):
                errors.append("Dealer notification recipients differ from affected dealers")
            for dealer, ids in expected["dealers"].items():
                calls = notified.get(dealer, [])
                if len(calls) != 1:
                    errors.append(f"{dealer}: expected exactly one dealer.notify, got {len(calls)}")
                if calls:
                    exact(f"{dealer} notified orders", [cid for group in calls for cid in group], ids)
            if bool(escalations) != expected["escalate"] or escalations > 1:
                errors.append(f"Expected {'one' if expected['escalate'] else 'no'} escalation, got {escalations}")
            for index, detail in enumerate(expected["details"]):
                if detail["kind"] not in {"noise", "unconfirmed"} and len(actions_per_incident[index]) < 3:
                    errors.append(f"Incident {index + 1}: fewer than three action kinds")
            # State equality verifies persisted effects, independently of action counts.
            for key, wanted in [("loaned", expected["loaners"]), ("held", expected["lots"]),
                                ("stopped", expected["stopped"]), ("customers", expected["owners"])]:
                if set(state[key]) != wanted:
                    errors.append(f"Replay final state {key} differs")
            if dict(state["notified"]) != expected["dealers"]:
                errors.append("Replay final dealer notification state differs")
            if trace_map is not None:
                trace = trace_map.get(eid)
                if trace is None:
                    errors.append("Missing event trace")
                else:
                    if trace.get("unresolved"):
                        errors.append("Trace has unresolved orders")
                    if len(trace.get("incidents", [])) != len(incidents):
                        errors.append("Trace incident count differs from parsed incidents")
                    for index, (detail, evidence) in enumerate(zip(expected["details"], trace.get("incidents", [])), 1):
                        if not evidence.get("reason"):
                            errors.append(f"Incident {index}: no decision rationale in trace")
                        if detail["kind"] not in {"noise", "unconfirmed"}:
                            paths = evidence.get("graph_paths", [])
                            if not paths or not all(self.valid_path(path) for path in paths):
                                errors.append(f"Incident {index}: missing or invalid table-backed graph path")
                            if detail["kind"] in {"supplier_delay", "plant_outage"}:
                                if set(evidence.get("affected_production_orders", [])) != detail["po"]:
                                    errors.append(f"Incident {index}: traced affected orders differ")
                            else:
                                vehicle_ids = {vin for vin, vehicle in self.vehicles.items()
                                               if vehicle["production_order_id"] in detail["po"]}
                                if set(evidence.get("affected_vehicles", [])) != vehicle_ids:
                                    errors.append(f"Incident {index}: traced affected vehicles differ")
                    logged_calls = [(r.get("tool"), r.get("args")) for r in rows]
                    traced_calls = [(r.get("tool"), r.get("args")) for r in trace.get("calls", [])]
                    if logged_calls != traced_calls:
                        errors.append("Trace calls differ from authoritative server action log")
            counts = {"affected_production_orders": len(expected["affected"]), "affected_customer_orders": len(expected["cos"]),
                      "dealers": len(expected["dealers"]), "eligible_loaner_orders": sum(map(len, expected["eligible"].values())),
                      "assigned_loaners": len(expected["loaners"]), "held_lots": len(expected["lots"]),
                      "stopped_vehicles": len(expected["stopped"]), "notified_owners": len(expected["owners"])}
            summaries.append({"event_id": eid, "passed": not errors, "errors": errors, "expected": counts,
                              "calls": len(rows), "write_calls": sum(r.get("tool") not in READS | {"escalate"} for r in rows),
                              "action_kinds_per_incident": [sorted(a) for a in actions_per_incident],
                              "baseline_passed": all(d["kind"] == "noise" for d in expected["details"])})
        passed = sum(row["passed"] for row in summaries)
        return {"audit": "independent direct-CSV expectations plus official Enterprise replay",
                "limitation": "Conditional on parsed incidents; not the hidden judging score. Text interpretation is separately reviewed in docs/evaluation.md.",
                "passed": not overall_errors and passed == len(public_events), "events_passed": passed,
                "events_total": len(public_events), "baseline_do_nothing_events_passed": sum(row["baseline_passed"] for row in summaries),
                "failed_log_calls": sum(row.get("ok") is not True for row in action_rows),
                "errors": overall_errors, "events": summaries}


def audit_run(data_dir, parsed, action_log, traces=None):
    """Accept loaded objects or paths; return a JSON-serializable audit report."""
    values = [parsed, action_log, traces]
    values = [load_json(v) if isinstance(v, (str, Path)) else v for v in values]
    return IndependentAudit(data_dir).audit(*values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--parsed", required=True)
    parser.add_argument("--action-log", required=True)
    parser.add_argument("--traces")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = audit_run(args.data, args.parsed, args.action_log, args.traces)
    rendered = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
