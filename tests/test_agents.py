"""Coordinator integration and bounded specialist dispatch on synthetic incidents."""
import unittest
from unittest.mock import Mock, patch

from src.agents import Coordinator, ProductionChanges, ScopedClient, ScopeViolation
from src.client import ToolCallError, UnknownOutcomeError

try:
    from tests.fixtures import SyntheticWorld, co, customer, po, vehicle
except ModuleNotFoundError:
    from fixtures import SyntheticWorld, co, customer, po, vehicle


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        self.world = SyntheticWorld(production_orders=[po("A", "2027-03-09"), po("OLD", "2027-03-04")], customer_orders=[co("CO-1", "A", "BUYER")], customers=[customer("BUYER", "Gold"), customer("OWNER", "Standard")], finished_vehicles=[vehicle("UNSOLD", "OLD"), vehicle("SOLD", "OLD", status="sold", owner="OWNER")])
        self.addCleanup(self.world.close)
        self.coordinator = Coordinator(self.world.graph, self.world.client)
        self.event = {"event_id": "SYNTHETIC", "text": "P_A outage on 2027-03-09."}
        self.outage = {"kind": "plant_outage", "confirmed": True, "plant_id": "P_A", "start_date": "2027-03-09", "end_date": "2027-03-09"}

    def parsed(self, *incidents):
        return {"event_id": "SYNTHETIC", "incidents": list(incidents), "provenance": {"model": "unit-test-extractor", "raw_output": "injected fixture"}}

    def test_event_id_mismatch_fails_before_any_call(self):
        parsed = self.parsed(self.outage)
        parsed["event_id"] = "DIFFERENT"
        with self.assertRaises(ValueError):
            self.coordinator.handle(self.event, parsed)
        self.assertEqual(self.world.client.calls, [])

    def quality_hold(self):
        return {"kind": "quality_hold", "confirmed": True, "lot_id": "LOT-X"}

    def test_three_specialists_are_actually_dispatched(self):
        with patch.object(self.coordinator.planner, "execute", wraps=self.coordinator.planner.execute) as planner, patch.object(self.coordinator.care, "execute", wraps=self.coordinator.care.execute) as care, patch.object(self.coordinator.quality, "execute", wraps=self.coordinator.quality.execute) as quality:
            trace = self.coordinator.handle(self.event, self.parsed(self.outage, self.quality_hold()))
        planner.assert_called_once()
        care.assert_called_once()
        quality.assert_called_once()
        self.assertEqual([step["agent"] for step in trace["agent_steps"]], ["Coordinator", "Supply Chain Planner", "Dealer Network / Customer Care", "Quality"])
        self.assertEqual(trace["architecture"]["coordinator"], "Coordinator")
        self.assertEqual(len(trace["architecture"]["specialists"]), 3)

    def test_coordinator_dispatches_only_specialists_with_work(self):
        with patch.object(self.coordinator.quality, "execute", wraps=self.coordinator.quality.execute) as quality:
            trace = self.coordinator.handle(self.event, self.parsed(self.outage))
        quality.assert_not_called()
        self.assertEqual(trace["agent_steps"][0]["dispatched"], ["Supply Chain Planner", "Dealer Network / Customer Care"])

    def test_typed_handoffs_chain_planner_into_customer_care(self):
        trace = self.coordinator.handle(self.event, self.parsed(self.outage, self.quality_hold()))
        chain = [(h["from"], h["to"], h["type"]) for h in trace["handoffs"]]
        self.assertEqual(chain, [
            ("Coordinator", "Supply Chain Planner", "WorkOrder"),
            ("Supply Chain Planner", "Dealer Network / Customer Care", "ProductionChanges"),
            ("Dealer Network / Customer Care", "Coordinator", "CustomerCareReport"),
            ("Coordinator", "Quality", "QualityOrder"),
            ("Quality", "Coordinator", "QualityReport")])
        changes = trace["handoffs"][1]["payload"]
        self.assertEqual(set(changes["moved"]), {"A"})
        self.assertEqual(trace["handoffs"][2]["payload"]["dealers_notified"], ["D1"])
        self.assertEqual(trace["handoffs"][4]["payload"]["lots_held"], ["LOT-X"])

    def test_every_call_is_attributed_to_an_agent_allowed_to_make_it(self):
        trace = self.coordinator.handle(self.event, self.parsed(self.outage, self.quality_hold()))
        arch = trace["architecture"]
        allowed = {s["name"]: set(s["allowed_tools"]) for s in arch["specialists"]}
        allowed["Coordinator"] = set(arch["coordinator_allowed_tools"])
        self.assertTrue(trace["calls"])
        for call in trace["calls"]:
            self.assertIn(call["tool"], allowed[call["role"]], call)

    def test_out_of_scope_tool_is_refused_before_any_server_call(self):
        def rogue(engine, changes):
            with engine.acting(self.coordinator.care):
                engine._call("mes.reschedule", {"production_order_id": "A", "new_date": "2027-03-12"}, "rogue")

        with patch.object(self.coordinator.care, "execute", side_effect=rogue):
            trace = self.coordinator.handle(self.event, self.parsed(self.outage))
        server_moves = [c for c in self.world.client.calls if c["tool"] == "mes.reschedule"]
        self.assertEqual(len(server_moves), 1)  # the planner's legitimate move only
        self.assertEqual(trace["status"], "halted")
        self.assertTrue(trace["error"]["scope_violation"])
        self.assertEqual(trace["error"]["agent"], "Dealer Network / Customer Care")
        self.assertFalse(any(c["tool"].startswith("dealer.") for c in self.world.client.calls))

    def test_scoped_client_never_forwards_refused_tool(self):
        base = Mock()
        client = ScopedClient(base, "Quality", {"quality.hold_lot"})
        with self.assertRaises(ScopeViolation):
            client.act("E", "mes.transfer", {})
        base.act.assert_not_called()
        client.act("E", "quality.hold_lot", {"lot_id": "L"})
        base.act.assert_called_once_with("E", "quality.hold_lot", {"lot_id": "L"})

    def test_customer_care_rejects_inconsistent_planner_handoff(self):
        with self.assertRaises(ValueError):
            self.coordinator.care.execute(None, ProductionChanges(["A", "B"], {"A": {}}, []))

    def test_confirmed_event_trace_has_graph_evidence_actions_and_provenance(self):
        trace = self.coordinator.handle(self.event, self.parsed(self.outage))
        self.assertEqual(trace["status"], "complete")
        self.assertEqual(trace["affected_production_orders"], ["A"])
        self.assertEqual(trace["write_count"], 3)
        self.assertEqual(trace["extraction"]["model"], "unit-test-extractor")
        self.assertEqual(trace["event"], self.event)
        paths = trace["incidents"][0]["graph_paths"]
        self.assertTrue(paths)
        self.assertTrue(all(path["nodes"][0] == "Plant:P_A" for path in paths))
        self.assertTrue(all(action["reason"] and action["role"] for action in trace["actions"]))
        self.assertTrue(trace["incidents"][0]["completeness"])

    def test_quality_specialist_executes_hold_stop_and_owner_notification(self):
        trace = self.coordinator.handle(self.event, self.parsed({"kind": "quality_hold", "confirmed": True, "lot_id": "LOT-X"}))
        self.assertEqual({action["tool"] for action in trace["actions"]}, {"quality.hold_lot", "dealer.stop_sale", "crm.notify_customer"})
        self.assertTrue(all(action["role"] == "Quality" for action in trace["actions"]))
        quality_step = next(step for step in trace["agent_steps"] if step["agent"] == "Quality")
        self.assertEqual(quality_step["quality_incidents"], 1)
        self.assertEqual(quality_step["actions"], 3)

    def test_noise_produces_explainable_trace_and_zero_calls(self):
        trace = self.coordinator.handle(self.event, self.parsed({"kind": "noise", "confirmed": False, "reason": "Brochure question."}))
        self.assertEqual(trace["status"], "no_action")
        self.assertEqual(trace["actions"], [])
        self.assertEqual(self.world.client.calls, [])
        self.assertEqual(trace["incidents"][0]["reason"], "Brochure question.")

    def test_unconfirmed_report_only_escalates(self):
        trace = self.coordinator.handle(self.event, self.parsed({"kind": "unconfirmed", "confirmed": False, "reason": "Unconfirmed rumor."}))
        self.assertEqual(trace["status"], "escalated")
        self.assertEqual([action["tool"] for action in trace["actions"]], ["escalate"])
        self.assertEqual(trace["write_count"], 0)

    def test_unknown_write_outcome_halts_without_retry_or_downstream_actions(self):
        original = self.world.client.act
        attempted = []

        def act(event_id, tool, args):
            attempted.append(tool)
            if tool == "mes.reschedule":
                raise UnknownOutcomeError("Connection lost after write")
            return original(event_id, tool, args)

        with patch.object(self.world.client, "act", side_effect=act):
            trace = self.coordinator.handle(self.event, self.parsed(self.outage))
        self.assertEqual(attempted.count("mes.reschedule"), 1)
        self.assertFalse(any(tool.startswith("dealer.") or tool.startswith("crm.") for tool in attempted))
        self.assertEqual(trace["status"], "halted")
        self.assertTrue(trace["error"]["unknown_outcome"])
        self.assertIn("Do not retry", trace["recovery"])
        self.assertEqual(trace["actions"], [])

    def test_rejected_write_halts_with_explicit_known_failure(self):
        original = self.world.client.act

        def act(event_id, tool, args):
            if tool == "mes.reschedule":
                raise ToolCallError("No free slot")
            return original(event_id, tool, args)

        with patch.object(self.world.client, "act", side_effect=act):
            trace = self.coordinator.handle(self.event, self.parsed(self.outage))
        self.assertEqual(trace["status"], "halted")
        self.assertFalse(trace["error"]["unknown_outcome"])
        self.assertEqual(trace["error"]["type"], "ToolCallError")


if __name__ == "__main__":
    unittest.main()
