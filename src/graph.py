"""Typed, auditable company graph built entirely from the supplied CSV tables.

The immutable graph describes the baseline world. Live schedules and loaner pools
must still be read from the enterprise server before an operational write.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

import networkx as nx


# table -> (ontology class, primary key); IDs are never inferred from event IDs.
ENTITY_TABLES = {
    "suppliers": ("Supplier", "supplier_id"),
    "parts": ("Part", "part_id"),
    "models": ("Model", "model"),
    "plants": ("Plant", "plant_id"),
    "production_orders": ("ProductionOrder", "production_order_id"),
    "customer_orders": ("CustomerOrder", "customer_order_id"),
    "customers": ("Customer", "customer_id"),
    "dealers": ("Dealer", "dealer_id"),
    "part_lots": ("Lot", "lot_id"),
    "finished_vehicles": ("Vehicle", "vin"),
    "inbound_shipments": ("Shipment", "shipment_id"),
}
SUPPORT_TABLES = ("bom", "plant_models", "loaners", "aliases", "calendar")
TODAY = "2027-03-08"


def _normalized(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


class KnowledgeGraph:
    """All 16 source tables, typed entity indexes, graph traversal and exports.

    Public indexes use CSV table stems and original primary IDs. Every graph node
    is namespaced, e.g. ``ProductionOrder:PO-0001``. Supporting tables annotate
    relationships or nodes; calendar and aliases remain in ``tables`` and export.
    Empty supporting tables are valid for synthetic policy tests.
    """

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.tables: dict[str, list[dict[str, str]]] = {}
        self.source_hashes: dict[str, str] = {}
        for stem in (*ENTITY_TABLES, *SUPPORT_TABLES):
            path = self.data_dir / f"{stem}.csv"
            if not path.exists() and stem in SUPPORT_TABLES:
                self.tables[stem] = []
                continue
            with path.open(encoding="utf-8-sig", newline="") as stream:
                self.tables[stem] = list(csv.DictReader(stream))
            self.source_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

        self.indexes: dict[str, dict[str, dict[str, str]]] = {}
        self.graph = nx.MultiDiGraph(description="Wacky Wheels baseline company graph")
        self.aliases: dict[tuple[str, str], set[str]] = defaultdict(set)
        for stem, (kind, primary_key) in ENTITY_TABLES.items():
            index = {}
            for row in self.tables[stem]:
                identity = row[primary_key]
                if not identity or identity in index:
                    raise ValueError(f"Missing or duplicate {primary_key}: {identity!r}")
                index[identity] = row
                self.graph.add_node(self.node_id(kind, identity), **row, type=kind,
                                    entity_id=identity, label=row.get("name") or identity,
                                    source_table=f"{stem}.csv")
                for alias in (identity, row.get("name", "")):
                    if alias:
                        self.aliases[(kind.casefold(), _normalized(alias))].add(identity)
            self.indexes[stem] = index

        self.models_by_part: dict[str, set[str]] = defaultdict(set)
        self.parts_by_model: dict[str, set[str]] = defaultdict(set)
        self.orders_by_plant: dict[str, set[str]] = defaultdict(set)
        self.orders_by_model: dict[str, set[str]] = defaultdict(set)
        self.cos_by_po: dict[str, set[str]] = defaultdict(set)
        self.vehicles_by_po: dict[str, set[str]] = defaultdict(set)
        self._build_relationships()

    @staticmethod
    def node_id(kind: str, identity: str) -> str:
        return f"{kind}:{identity}"

    def _edge(self, source_kind: str, source_id: str, relation: str,
              target_kind: str, target_id: str, source_table: str) -> None:
        source, target = self.node_id(source_kind, source_id), self.node_id(target_kind, target_id)
        missing = [node for node in (source, target) if node not in self.graph]
        if missing:
            raise ValueError(f"Dangling {relation} relationship in {source_table}: {missing}")
        # A relation may be evidenced by multiple shipments; do not multiply an
        # identical Supplier -> Part relationship for each shipment.
        self.graph.add_edge(source, target, key=relation, relation=relation, source_table=source_table)

    def _build_relationships(self) -> None:
        edge = self._edge
        for row in self.tables["bom"]:
            model, part = row["model"], row["part_id"]
            self.parts_by_model[model].add(part)
            self.models_by_part[part].add(model)
            edge("Part", part, "USED_BY", "Model", model, "bom.csv")
        for row in self.tables["plant_models"]:
            edge("Plant", row["plant_id"], "BUILDS", "Model", row["model"], "plant_models.csv")
        for row in self.tables["production_orders"]:
            po, model, plant = row["production_order_id"], row["model"], row["plant_id"]
            self.orders_by_plant[plant].add(po)
            self.orders_by_model[model].add(po)
            edge("Plant", plant, "SCHEDULES", "ProductionOrder", po, "production_orders.csv")
            edge("Model", model, "HAS_ORDER", "ProductionOrder", po, "production_orders.csv")
        for row in self.tables["customer_orders"]:
            co, po = row["customer_order_id"], row["production_order_id"]
            self.cos_by_po[po].add(co)
            edge("ProductionOrder", po, "FULFILLS", "CustomerOrder", co, "customer_orders.csv")
            edge("CustomerOrder", co, "AT_DEALER", "Dealer", row["dealer_id"], "customer_orders.csv")
            edge("CustomerOrder", co, "FOR_CUSTOMER", "Customer", row["customer_id"], "customer_orders.csv")
        for row in self.tables["finished_vehicles"]:
            vin, po = row["vin"], row["production_order_id"]
            self.vehicles_by_po[po].add(vin)
            edge("ProductionOrder", po, "BUILT", "Vehicle", vin, "finished_vehicles.csv")
            edge("Vehicle", vin, "AT_DEALER", "Dealer", row["dealer_id"], "finished_vehicles.csv")
            if row["customer_id"]:
                edge("Vehicle", vin, "OWNED_BY", "Customer", row["customer_id"], "finished_vehicles.csv")
        for row in self.tables["inbound_shipments"]:
            shipment, supplier, part = row["shipment_id"], row["supplier_id"], row["part_id"]
            edge("Supplier", supplier, "SHIPS", "Shipment", shipment, "inbound_shipments.csv")
            edge("Supplier", supplier, "SUPPLIES", "Part", part, "inbound_shipments.csv")
            edge("Shipment", shipment, "CONTAINS", "Part", part, "inbound_shipments.csv")
            edge("Shipment", shipment, "RECEIVED_AT", "Plant", row["plant_id"], "inbound_shipments.csv")
        for row in self.tables["part_lots"]:
            lot, part, plant = row["lot_id"], row["part_id"], row["plant_id"]
            edge("Supplier", row["supplier_id"], "PRODUCES", "Lot", lot, "part_lots.csv")
            edge("Lot", lot, "OF_PART", "Part", part, "part_lots.csv")
            edge("Lot", lot, "AT_PLANT", "Plant", plant, "part_lots.csv")
            # Rule 6: the lot window, receiving plant, and BOM jointly define use.
            models = self.models_by_part[part]
            for po in sorted(self.orders_by_plant[plant]):
                order = self.indexes["production_orders"][po]
                if (order["model"] in models and
                        row["first_build_date"] <= order["build_date"] <= row["last_build_date"]):
                    edge("Lot", lot, "USED_IN", "ProductionOrder", po,
                         "part_lots.csv + production_orders.csv + bom.csv")
        for row in self.tables["loaners"]:
            node = self.node_id("Dealer", row["dealer_id"])
            if node not in self.graph:
                raise ValueError(f"Unknown dealer in loaners.csv: {row['dealer_id']}")
            self.graph.nodes[node]["baseline_loaners"] = int(row["loaners_available"])
        for row in self.tables["aliases"]:
            self.aliases[(row["entity_type"].casefold(), _normalized(row["alias"]))].add(row["entity_id"])

    def resolve_alias(self, text: str, entity_type: str | None = None) -> str:
        """Resolve an exact ID, canonical name, or supplied alias; ambiguity fails closed."""
        normalized = _normalized(text)
        if entity_type:
            matches = self.aliases.get((entity_type.casefold(), normalized), set())
        else:
            matches = set().union(*(ids for (_, alias), ids in self.aliases.items() if alias == normalized))
        if len(matches) != 1:
            raise ValueError(f"{'Unknown' if not matches else 'Ambiguous'} entity alias: {text!r}")
        return next(iter(matches))

    def related(self, kind: str, identity: str, relation: str) -> list[str]:
        """Traverse a typed outgoing graph relation and return primary IDs."""
        node = self.node_id(kind, identity)
        if node not in self.graph:
            raise ValueError(f"Unknown graph entity: {node}")
        return sorted({self.graph.nodes[target]["entity_id"]
                       for _, target, attributes in self.graph.out_edges(node, data=True)
                       if attributes["relation"] == relation})

    def affected_delay(self, shipment_id: str, new_eta: str) -> list[str]:
        """Rule 1, graph traversal with [original ETA, new ETA) at receiving plant."""
        shipment = self.indexes["inbound_shipments"][shipment_id]
        date.fromisoformat(new_eta)
        if new_eta <= shipment["eta_date"]:
            raise ValueError("A delayed shipment must have a later new ETA")
        models = self.related("Part", shipment["part_id"], "USED_BY")
        affected = []
        for model in models:
            for po in self.related("Model", model, "HAS_ORDER"):
                order = self.indexes["production_orders"][po]
                if (order["plant_id"] == shipment["plant_id"] and
                        shipment["eta_date"] <= order["build_date"] < new_eta and
                        order["build_date"] >= TODAY):
                    affected.append(po)
        return sorted(set(affected))

    def affected_outage(self, plant_id: str, start_date: str, end_date: str) -> list[str]:
        """Rule 2, inclusive outage interval; never include already-built orders."""
        date.fromisoformat(start_date)
        date.fromisoformat(end_date)
        if end_date < start_date:
            raise ValueError("Outage ends before it starts")
        return [po for po in self.related("Plant", plant_id, "SCHEDULES")
                if max(start_date, TODAY) <= self.indexes["production_orders"][po]["build_date"] <= end_date]

    def affected_quality(self, lot_id: str) -> list[str]:
        """Rule 6, Lot -> eligible ProductionOrder -> finished Vehicle traversal."""
        lot = self.indexes["part_lots"][lot_id]
        vins = set()
        for po in self.related("Lot", lot_id, "USED_IN"):
            for vin in self.related("ProductionOrder", po, "BUILT"):
                vehicle = self.indexes["finished_vehicles"][vin]
                if (vehicle["plant_id"] == lot["plant_id"] and
                        lot["first_build_date"] <= vehicle["build_date"] <= lot["last_build_date"]):
                    vins.add(vin)
        return sorted(vins)

    def customer_orders_for(self, po_ids: Iterable[str]) -> list[str]:
        return sorted({co for po in po_ids for co in self.related("ProductionOrder", po, "FULFILLS")})

    def path(self, nodes: Iterable[tuple[str, str]]) -> dict:
        """Return evidence only when each consecutive edge actually exists."""
        keys = [self.node_id(kind, identity) for kind, identity in nodes]
        for key in keys:
            if key not in self.graph:
                raise ValueError(f"Unknown graph entity: {key}")
        edges = []
        for source, target in zip(keys, keys[1:]):
            links = self.graph.get_edge_data(source, target)
            if not links:
                raise ValueError(f"No graph edge: {source} -> {target}")
            relation = sorted(links)[0]
            edges.append({"source": source, "target": target, **links[relation]})
        return {"nodes": keys, "edges": edges, "text": " -> ".join(keys)}

    def _order_paths(self, prefix: list[tuple[str, str]], po_ids: Iterable[str],
                     max_paths: int | None) -> list[dict]:
        paths = []
        for po in sorted(set(po_ids)):
            order_prefix = prefix + [("ProductionOrder", po)]
            cos = self.related("ProductionOrder", po, "FULFILLS")
            if not cos:
                paths.append(self.path(order_prefix))
            for co in cos:
                row = self.indexes["customer_orders"][co]
                for kind, key in (("Dealer", "dealer_id"), ("Customer", "customer_id")):
                    paths.append(self.path(order_prefix + [("CustomerOrder", co), (kind, row[key])]))
                    if max_paths is not None and len(paths) >= max_paths:
                        return paths[:max_paths]
            if max_paths is not None and len(paths) >= max_paths:
                return paths[:max_paths]
        return paths

    def paths_for_delay(self, shipment_id: str, po_ids: Iterable[str] | None = None,
                        *, new_eta: str | None = None, max_paths: int | None = 12) -> list[dict]:
        if po_ids is None:
            if new_eta is None:
                raise ValueError("Provide affected po_ids or new_eta")
            po_ids = self.affected_delay(shipment_id, new_eta)
        shipment = self.indexes["inbound_shipments"][shipment_id]
        by_model: dict[str, list[str]] = defaultdict(list)
        for po in po_ids:
            by_model[self.indexes["production_orders"][po]["model"]].append(po)
        paths = []
        for model, orders in sorted(by_model.items()):
            prefix = [("Shipment", shipment_id), ("Part", shipment["part_id"]), ("Model", model)]
            remaining = None if max_paths is None else max_paths - len(paths)
            if remaining == 0:
                break
            paths.extend(self._order_paths(prefix, orders, remaining))
        return paths

    def paths_for_outage(self, plant_id: str, po_ids: Iterable[str],
                         *, max_paths: int | None = 12) -> list[dict]:
        return self._order_paths([("Plant", plant_id)], po_ids, max_paths)

    def paths_for_quality(self, lot_id: str, *, max_paths: int | None = 12) -> list[dict]:
        paths = []
        for vin in self.affected_quality(lot_id):
            row = self.indexes["finished_vehicles"][vin]
            tail = (("Customer", row["customer_id"]) if row["status"] == "sold" and row["customer_id"]
                    else ("Dealer", row["dealer_id"]))
            paths.append(self.path([("Lot", lot_id), ("ProductionOrder", row["production_order_id"]),
                                    ("Vehicle", vin), tail]))
            if max_paths is not None and len(paths) >= max_paths:
                break
        return paths

    def summary(self) -> dict:
        return {"nodes": self.graph.number_of_nodes(), "edges": self.graph.number_of_edges(),
                "entity_counts": dict(sorted(Counter(nx.get_node_attributes(self.graph, "type").values()).items())),
                "relation_counts": dict(sorted(Counter(a["relation"] for _, _, a in self.graph.edges(data=True)).items())),
                "table_rows": {stem: len(rows) for stem, rows in sorted(self.tables.items())},
                "source_sha256": dict(sorted(self.source_hashes.items())),
                "world_today": TODAY, "mutable_state": "Baseline only; read server before writes"}

    def export(self, out_dir: str | Path) -> dict:
        """Portable full graph, all supporting rows, integrity summary and class diagram."""
        output = Path(out_dir)
        output.mkdir(parents=True, exist_ok=True)
        summary = self.summary()
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        payload = {"directed": True, "multigraph": True,
                   "nodes": [{"id": node, **attrs} for node, attrs in self.graph.nodes(data=True)],
                   "edges": [{"source": source, "target": target, **attrs}
                             for source, target, attrs in self.graph.edges(data=True)],
                   "supporting_tables": {stem: self.tables[stem] for stem in SUPPORT_TABLES}}
        (output / "graph.json").write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
        nx.write_graphml(self.graph, output / "graph.graphml")
        class_edges = sorted({(self.graph.nodes[source]["type"], attrs["relation"], self.graph.nodes[target]["type"])
                              for source, target, attrs in self.graph.edges(data=True)})
        mermaid = "flowchart LR\n" + "".join(f"    {source} -->|{relation}| {target}\n"
                                              for source, relation, target in class_edges)
        (output / "ontology.mmd").write_text(mermaid, encoding="utf-8")
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Directory containing the company CSV files")
    parser.add_argument("--out", default="outputs/ontology")
    args = parser.parse_args()
    print(json.dumps(KnowledgeGraph(args.data).export(args.out), indent=2))


if __name__ == "__main__":
    main()
