"""Tiny generated enterprise worlds; no answer data from the challenge feed."""
from __future__ import annotations

import csv
import importlib.util
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ENTERPRISE_FILE = ROOT / "starter" / "enterprise.py"
if not ENTERPRISE_FILE.exists():
    ENTERPRISE_FILE = Path(r"C:\Users\asus\Desktop\MS\Datathon\challenges\challenge-6\data\package\hack_the_highway_package\enterprise.py")
spec = importlib.util.spec_from_file_location("fixture_enterprise", ENTERPRISE_FILE)
enterprise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enterprise)

HEADERS = {
    "plants": "plant_id,name,city,slots_per_day",
    "models": "model,segment",
    "plant_models": "plant_id,model",
    "parts": "part_id,name,category",
    "suppliers": "supplier_id,name,city",
    "bom": "model,part_id",
    "inbound_shipments": "shipment_id,supplier_id,part_id,plant_id,eta_date,covers_days",
    "production_orders": "production_order_id,plant_id,build_date,model,units",
    "customer_orders": "customer_order_id,production_order_id,dealer_id,customer_id,model,promised_date",
    "customers": "customer_id,name,tier",
    "dealers": "dealer_id,name,city,region,transit_days",
    "loaners": "dealer_id,loaners_available",
    "part_lots": "lot_id,part_id,supplier_id,plant_id,first_build_date,last_build_date",
    "finished_vehicles": "vin,production_order_id,model,plant_id,build_date,dealer_id,status,customer_id",
    "aliases": "alias,entity_type,entity_id",
    "calendar": "day_index,date,weekday",
}


def row(table, *values):
    return dict(zip(HEADERS[table].split(","), map(str, values)))


def po(ident, day, plant="P_A", model="M1"):
    return row("production_orders", ident, plant, day, model, 10)


def co(ident, production_order, customer=None, dealer="D1", promised="2027-03-15"):
    return row("customer_orders", ident, production_order, dealer, customer or "C" + ident, "M1", promised)


def customer(ident, tier="Gold"):
    return row("customers", ident, ident, tier)


def vehicle(ident, production_order, day="2027-03-04", plant="P_A", model="M1", status="in_stock", owner="", dealer="D1"):
    return row("finished_vehicles", ident, production_order, model, plant, day, dealer, status, owner)


def base_tables():
    tables = {name: [] for name in HEADERS}
    tables.update({
        "plants": [row("plants", "P_A", "Alpha", "Alpha City", 2), row("plants", "P_B", "Beta", "Beta City", 2), row("plants", "P_C", "Gamma", "Gamma City", 2)],
        "models": [row("models", "M1", "Sedan"), row("models", "M2", "SUV")],
        "plant_models": [row("plant_models", plant, model) for plant, model in [("P_A", "M1"), ("P_A", "M2"), ("P_B", "M1"), ("P_C", "M2")]],
        "parts": [row("parts", "PART-X", "Part X", "component"), row("parts", "PART-Y", "Part Y", "component")],
        "suppliers": [row("suppliers", "SUP-1", "Parts supplier", "Supplier City")],
        "bom": [row("bom", "M1", "PART-X"), row("bom", "M2", "PART-Y")],
        "inbound_shipments": [row("inbound_shipments", "SH-X", "SUP-1", "PART-X", "P_A", "2027-03-09", 5)],
        "dealers": [row("dealers", d, d, "City", "South", 2) for d in ("D1", "D2")],
        "loaners": [row("loaners", "D1", 2), row("loaners", "D2", 1)],
        "part_lots": [row("part_lots", "LOT-X", "PART-X", "SUP-1", "P_A", "2027-03-04", "2027-03-05")],
        "calendar": [row("calendar", i, enterprise.idx_to_date(i).isoformat(), enterprise.idx_to_date(i).strftime("%A")) for i in range(-10, 20)],
    })
    return tables


class InMemoryClient:
    """Runs the unmodified public enterprise tool implementation and records failures."""
    def __init__(self, data_dir):
        self.enterprise = enterprise.Enterprise(str(data_dir))
        self.calls = []

    def act(self, event_id, tool, args):
        record = {"event_id": event_id, "tool": tool, "args": dict(args), "ok": False}
        self.calls.append(record)
        result = self.enterprise.call(event_id, tool, args)
        record.update(ok=True, result=result)
        return result

    @property
    def writes(self):
        return [r for r in self.calls if r["tool"] in enterprise.WRITE_TOOLS]


class SyntheticWorld:
    def __init__(self, **overrides):
        from src.graph import KnowledgeGraph
        from src.policy import PolicyEngine
        self.scratch_root = (ROOT / "runs" / "test_tmp").resolve()
        self.scratch_root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(prefix="highway-policy-", dir=self.scratch_root)
        self.path = Path(self.temp.name).resolve()
        if self.scratch_root not in self.path.parents:
            raise RuntimeError("Synthetic fixture escaped workspace scratch directory")
        self.tables = base_tables()
        self.tables.update(overrides)
        for name, fields in HEADERS.items():
            with (self.path / (name + ".csv")).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields.split(","))
                writer.writeheader()
                writer.writerows(self.tables[name])
        self.graph = KnowledgeGraph(self.path)
        self.client = InMemoryClient(self.path)
        self.engine = PolicyEngine(self.graph, self.client)

    def run(self, incidents, event_id="TEST"):
        return self.engine.handle(event_id, incidents)

    def state(self, event_id="TEST"):
        return self.client.enterprise.state(event_id)

    def close(self):
        if self.scratch_root not in Path(self.temp.name).resolve().parents:
            raise RuntimeError("Refusing cleanup outside workspace scratch directory")
        self.temp.cleanup()
