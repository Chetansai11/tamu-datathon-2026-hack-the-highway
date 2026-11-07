"""Executable handbook rules over synthetic worlds, independent of the event feed.

Run from repo root: python -m unittest discover -s tests -v
"""
import unittest
from datetime import date, timedelta

try:
    from tests.fixtures import SyntheticWorld, co, customer, enterprise, po, row, vehicle
except ModuleNotFoundError:
    from fixtures import SyntheticWorld, co, customer, enterprise, po, row, vehicle


def outage(start="2027-03-09", end="2027-03-09", plant="P_A"):
    return {"kind": "plant_outage", "plant_id": plant, "start_date": start, "end_date": end, "confirmed": True}


def delay(eta="2027-03-11"):
    return {"kind": "supplier_delay", "shipment_id": "SH-X", "part_id": "PART-X", "plant_id": "P_A", "new_eta": eta, "confirmed": True}


class PolicyRulesTest(unittest.TestCase):
    def world(self, **tables):
        world = SyntheticWorld(**tables)
        self.addCleanup(world.close)
        return world

    def moves(self, world):
        return [r for r in world.client.writes if r["tool"] in {"mes.reschedule", "mes.transfer"}]

    def assertNoFailures(self, world):
        self.assertTrue(all(r["ok"] for r in world.client.calls), world.client.calls)

    def test_rule1_delay_is_half_open_and_plant_and_bom_scoped(self):
        world = self.world(production_orders=[
            po("BEFORE", "2027-03-08"), po("START", "2027-03-09"),
            po("INSIDE", "2027-03-10"), po("END", "2027-03-11"),
            po("OTHER_PLANT", "2027-03-09", "P_B"), po("OTHER_MODEL", "2027-03-09", model="M2"),
        ])
        world.run([delay()])
        self.assertEqual({r["args"]["production_order_id"] for r in self.moves(world)}, {"START", "INSIDE"})
        self.assertTrue(all(r["args"]["new_date"] >= "2027-03-11" for r in self.moves(world)))
        self.assertNoFailures(world)

    def test_rule2_outage_includes_both_endpoints(self):
        world = self.world(production_orders=[po("BEFORE", "2027-03-08"), po("START", "2027-03-09"), po("END", "2027-03-10"), po("AFTER", "2027-03-11"), po("OTHER", "2027-03-09", "P_B")])
        world.run([outage(end="2027-03-10")])
        self.assertEqual({r["args"]["production_order_id"] for r in self.moves(world)}, {"START", "END"})
        self.assertNoFailures(world)

    def test_rule2_friday_outage_restarts_monday(self):
        world = self.world(production_orders=[po("A", "2027-03-12")])
        world.run([outage("2027-03-12", "2027-03-12")])
        self.assertEqual(self.moves(world)[0]["args"]["new_date"], "2027-03-15")
        self.assertNoFailures(world)

    def test_rule3_earliest_same_plant_slot_and_capacity(self):
        world = self.world(production_orders=[po("A", "2027-03-09"), po("B", "2027-03-09"), po("FIXED", "2027-03-10")])
        world.run([outage()])
        dates = sorted(r["args"]["new_date"] for r in self.moves(world))
        self.assertEqual(dates, ["2027-03-10", "2027-03-11"])
        self.assertTrue(all(r["tool"] == "mes.reschedule" for r in self.moves(world)))
        self.assertNoFailures(world)

    def test_rule3_prefer_late_same_plant_slot_over_early_transfer(self):
        orders = [po("A", "2027-03-09")]
        for i in range(2, 19):
            day = enterprise.idx_to_date(i).isoformat()
            orders += [po(f"F{i}a", day), po(f"F{i}b", day)]
        world = self.world(production_orders=orders)
        world.run([outage()])
        self.assertEqual(self.moves(world)[0]["tool"], "mes.reschedule")
        self.assertEqual(self.moves(world)[0]["args"]["new_date"], "2027-04-02")
        self.assertNoFailures(world)

    def test_rule3_transfer_when_no_same_plant_slot_uses_any_available_day(self):
        orders = [po("A", "2027-03-09")]
        for i in range(2, 20):
            day = enterprise.idx_to_date(i).isoformat()
            orders += [po(f"F{i}a", day), po(f"F{i}b", day)]
        world = self.world(production_orders=orders)
        world.run([outage()])
        self.assertEqual(self.moves(world)[0]["tool"], "mes.transfer")
        self.assertEqual(self.moves(world)[0]["args"]["to_plant_id"], "P_B")
        self.assertEqual(self.moves(world)[0]["args"]["new_date"], "2027-03-08")
        self.assertNoFailures(world)

    def test_rule3_transfer_cannot_use_plant_that_does_not_build_model(self):
        orders = [po("A", "2027-03-09")]
        for i in range(20):
            day = enterprise.idx_to_date(i).isoformat()
            if i >= 2:
                orders += [po(f"A{i}a", day), po(f"A{i}b", day)]
            orders += [po(f"B{i}a", day, "P_B"), po(f"B{i}b", day, "P_B")]
        world = self.world(production_orders=orders)
        world.run([outage()])
        self.assertEqual(self.moves(world), [])
        self.assertTrue(any(r["tool"] == "escalate" for r in world.client.calls))
        self.assertNoFailures(world)

    def test_rule4_one_notification_per_dealer_with_exact_affected_orders(self):
        world = self.world(
            production_orders=[po("A", "2027-03-09"), po("B", "2027-03-10"), po("SAFE", "2027-03-08")],
            customer_orders=[co("CO-1", "A", "C1"), co("CO-2", "B", "C2"), co("CO-3", "A", "C3", "D2"), co("CO-SAFE", "SAFE", "C4")],
            customers=[customer("C1"), customer("C2"), customer("C3"), customer("C4")],
        )
        world.run([outage(end="2027-03-10")])
        notifications = [r for r in world.client.writes if r["tool"] == "dealer.notify"]
        self.assertEqual(len(notifications), 2)
        actual = {r["args"]["dealer_id"]: set(r["args"]["customer_order_ids"]) for r in notifications}
        self.assertEqual(actual, {"D1": {"CO-1", "CO-2"}, "D2": {"CO-3"}})
        self.assertNoFailures(world)

    def test_rule5_priority_tier_then_promised_date_then_order_id(self):
        ids = ["CO-10", "CO-20", "CO-30", "CO-40", "CO-50", "CO-60"]
        customers = [customer("C1", "Gold"), customer("C2", "Platinum"), customer("C3", "Platinum"), customer("C4", "Platinum"), customer("C5", "Gold"), customer("C6", "Standard")]
        promised = ["2027-03-08", "2027-03-15", "2027-03-12", "2027-03-12", "2027-03-08", "2027-03-08"]
        world = self.world(production_orders=[po("A", "2027-03-09")], customer_orders=[co(ident, "A", f"C{i+1}", promised=promised[i]) for i, ident in enumerate(ids)], customers=customers, loaners=[row("loaners", "D1", 4), row("loaners", "D2", 0)])
        world.run([outage()])
        assignments = [r["args"]["customer_order_id"] for r in world.client.writes if r["tool"] == "crm.assign_loaner"]
        self.assertEqual(assignments, ["CO-30", "CO-40", "CO-20", "CO-10"])
        self.assertEqual(world.state()["loaners"]["D1"], 0)
        self.assertNoFailures(world)

    def test_rule5_standard_never_gets_loaner_even_with_spare_pool(self):
        world = self.world(production_orders=[po("A", "2027-03-09")], customer_orders=[co("CO-1", "A", "C1")], customers=[customer("C1", "Standard")])
        world.run([outage()])
        self.assertFalse(any(r["tool"] == "crm.assign_loaner" for r in world.client.calls))
        self.assertEqual(world.state()["notified"]["D1"], {"CO-1"})
        self.assertNoFailures(world)

    def test_rule5_zero_pool_produces_no_failed_assignment(self):
        world = self.world(production_orders=[po("A", "2027-03-09")], customer_orders=[co("CO-1", "A", "C1")], customers=[customer("C1", "Gold")], loaners=[row("loaners", "D1", 0), row("loaners", "D2", 0)])
        world.run([outage()])
        self.assertEqual(world.state()["loaned"], set())
        self.assertNoFailures(world)

    def test_rule6_hold_lot_and_split_sold_from_unsold_with_exact_scope(self):
        orders = [po("OLD-A", "2027-03-04"), po("OLD-B", "2027-03-05"), po("OLD-C", "2027-03-03"), po("OLD-D", "2027-03-04", "P_B"), po("OLD-E", "2027-03-04", model="M2")]
        world = self.world(production_orders=orders, customers=[customer("OWNER")], finished_vehicles=[vehicle("UNSOLD", "OLD-A"), vehicle("SOLD", "OLD-B", day="2027-03-05", status="sold", owner="OWNER"), vehicle("BEFORE", "OLD-C", day="2027-03-03"), vehicle("OTHER_PLANT", "OLD-D", plant="P_B"), vehicle("OTHER_MODEL", "OLD-E", model="M2")])
        world.run([{"kind": "quality_hold", "lot_id": "LOT-X", "confirmed": True}])
        self.assertEqual(world.state()["held"], {"LOT-X"})
        self.assertEqual(world.state()["stopped"], {"UNSOLD"})
        self.assertEqual(world.state()["customers"], {"OWNER"})
        self.assertEqual({r["tool"] for r in world.client.writes}, {"quality.hold_lot", "dealer.stop_sale", "crm.notify_customer"})
        self.assertNoFailures(world)

    def test_rule6_batches_unsold_by_dealer_and_notifies_each_owner_once(self):
        world = self.world(production_orders=[po("OLD-A", "2027-03-04")], customers=[customer("OWNER")], finished_vehicles=[vehicle("STOCK-1", "OLD-A"), vehicle("STOCK-2", "OLD-A"), vehicle("SOLD-1", "OLD-A", status="sold", owner="OWNER"), vehicle("SOLD-2", "OLD-A", status="sold", owner="OWNER")])
        world.run([{"kind": "quality_hold", "lot_id": "LOT-X", "confirmed": True}])
        stops = [r for r in world.client.writes if r["tool"] == "dealer.stop_sale"]
        owners = [r for r in world.client.writes if r["tool"] == "crm.notify_customer"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(set(stops[0]["args"]["vins"]), {"STOCK-1", "STOCK-2"})
        self.assertEqual(len(owners), 1)
        self.assertNoFailures(world)

    def test_rule7_noise_is_no_operation(self):
        world = self.world(production_orders=[po("A", "2027-03-09")])
        world.run([{"kind": "noise", "confirmed": True, "reason": "Unrelated brochure request"}])
        self.assertEqual(world.client.calls, [])

    def test_rule8_rumor_escalates_only(self):
        world = self.world(production_orders=[po("A", "2027-03-09")])
        world.run([{"kind": "unconfirmed", "confirmed": False, "reason": "Unverified disruption"}])
        self.assertEqual([r["tool"] for r in world.client.calls], ["escalate"])
        self.assertEqual(world.client.writes, [])

    def test_rule8_unconfirmed_typed_incident_does_not_move_orders(self):
        world = self.world(production_orders=[po("A", "2027-03-09")])
        incident = outage()
        incident["confirmed"] = False
        world.run([incident])
        self.assertEqual([r["tool"] for r in world.client.calls], ["escalate"])
        self.assertEqual(world.client.writes, [])

    def test_rule8_missing_dates_escalates_without_operational_write(self):
        world = self.world(production_orders=[po("A", "2027-03-09")])
        world.run([{"kind": "plant_outage", "plant_id": "P_A", "confirmed": True}])
        self.assertEqual([r["tool"] for r in world.client.calls], ["escalate"])
        self.assertEqual(world.client.writes, [])

    def test_rule9_real_incident_has_three_valid_action_kinds(self):
        world = self.world(production_orders=[po("A", "2027-03-09")], customer_orders=[co("CO-1", "A", "C1")], customers=[customer("C1", "Gold")])
        world.run([outage()])
        self.assertEqual({r["tool"] for r in world.client.writes}, {"mes.reschedule", "dealer.notify", "crm.assign_loaner"})
        self.assertNoFailures(world)

    def test_rule10_no_affected_records_does_not_invent_writes(self):
        world = self.world(production_orders=[po("SAFE", "2027-03-08")])
        world.run([outage()])
        self.assertEqual(world.client.writes, [])

    def test_compound_unions_notifications_and_ranks_loaners_across_incidents(self):
        world = self.world(production_orders=[po("A", "2027-03-09"), po("B", "2027-03-09", "P_B")], customer_orders=[co("CO-GOLD", "A", "GOLD"), co("CO-PLAT", "B", "PLAT")], customers=[customer("GOLD", "Gold"), customer("PLAT", "Platinum")], loaners=[row("loaners", "D1", 1), row("loaners", "D2", 0)])
        world.run([outage(), outage(plant="P_B")])
        notifications = [r for r in world.client.writes if r["tool"] == "dealer.notify"]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(set(notifications[0]["args"]["customer_order_ids"]), {"CO-GOLD", "CO-PLAT"})
        self.assertEqual(world.state()["loaned"], {"CO-PLAT"})
        self.assertNoFailures(world)

    def test_compound_overlapping_incidents_move_order_once_past_both(self):
        world = self.world(production_orders=[po("A", "2027-03-09")])
        world.run([outage(), delay("2027-03-12")])
        self.assertEqual(len(self.moves(world)), 1)
        self.assertEqual(self.moves(world)[0]["args"]["new_date"], "2027-03-12")
        self.assertNoFailures(world)

    def test_compound_disjoint_orders_share_capacity(self):
        world = self.world(production_orders=[po("A", "2027-03-09"), po("B", "2027-03-10"), po("FIXED", "2027-03-11")])
        world.run([outage(), outage("2027-03-10", "2027-03-10")])
        self.assertEqual(sorted(r["args"]["new_date"] for r in self.moves(world)), ["2027-03-11", "2027-03-12"])
        self.assertNoFailures(world)

    def test_distinct_events_each_start_in_fresh_world(self):
        world = self.world(production_orders=[po("A", "2027-03-09")], customer_orders=[co("CO-1", "A", "C1")], customers=[customer("C1")], loaners=[row("loaners", "D1", 1), row("loaners", "D2", 0)])
        world.run([outage()], event_id="FIRST")
        world.run([outage()], event_id="SECOND")
        self.assertEqual(world.state("FIRST")["loaned"], {"CO-1"})
        self.assertEqual(world.state("SECOND")["loaned"], {"CO-1"})
        self.assertEqual(world.state("FIRST")["loc"]["A"], world.state("SECOND")["loc"]["A"])
        self.assertNoFailures(world)

    def test_slot_write_has_immediately_preceding_live_schedule_read(self):
        world = self.world(production_orders=[po("A", "2027-03-09"), po("B", "2027-03-09")])
        world.run([outage()])
        for index, record in enumerate(world.client.calls):
            if record["tool"] in {"mes.reschedule", "mes.transfer"}:
                self.assertGreater(index, 0)
                previous = world.client.calls[index - 1]
                self.assertEqual(previous["tool"], "mes.get_schedule")
                self.assertEqual(previous["args"]["date"], record["args"]["new_date"])
        self.assertNoFailures(world)


if __name__ == "__main__":
    unittest.main()
