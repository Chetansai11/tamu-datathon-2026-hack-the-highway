"""Model-free parser guardrails over generated company data and injected outputs."""
import json
import unittest
from unittest.mock import patch

from src.parse import EventParser, ExtractionError, normalize_incident, normalize_incidents, parse_json_output, resolve_date

try:
    from tests.fixtures import SyntheticWorld, row
except ModuleNotFoundError:
    from fixtures import SyntheticWorld, row


class ParserGuardrailsTest(unittest.TestCase):
    def setUp(self):
        self.world = SyntheticWorld(aliases=[row("aliases", "the Alpha line", "plant", "P_A"), row("aliases", "widgets", "part", "PART-X"), row("aliases", "Acme", "supplier", "SUP-1")])
        self.addCleanup(self.world.close)
        self.graph = self.world.graph

    def test_relative_dates_use_explicit_calendar_week_convention(self):
        cases = {"next Monday": "2027-03-15", "next Tuesday": "2027-03-16", "next Wednesday": "2027-03-17", "next Friday": "2027-03-19", "last Monday": "2027-03-01", "last Thursday": "2027-03-04", "this Friday": "2027-03-12", "today": "2027-03-08", "day after tomorrow": "2027-03-10"}
        for wording, expected in cases.items():
            with self.subTest(wording=wording):
                self.assertEqual(resolve_date(wording), expected)

    def test_absolute_dates_and_ordinal_spans(self):
        for text in ("Thursday Mar 4", "4th March 2027", "2027-03-04", "Thursday March 4th, 2027"):
            with self.subTest(text=text):
                self.assertEqual(resolve_date(text), "2027-03-04")

    def test_contradictory_weekday_and_invalid_date_rejected(self):
        for text in ("Friday Mar 4", "2027-02-30", "soon", "", "03/04/2027"):
            with self.subTest(text=text), self.assertRaises(ExtractionError):
                resolve_date(text)

    def test_outage_alias_and_relative_dates_resolved_in_code(self):
        text = "The Alpha line is down from next Tuesday through next Thursday."
        incident = normalize_incident({"kind": "plant_outage", "confirmed": True, "plant": "the Alpha line", "start": "next Tuesday", "end": "next Thursday"}, text, self.graph)
        self.assertEqual((incident["plant_id"], incident["start_date"], incident["end_date"]), ("P_A", "2027-03-16", "2027-03-18"))

    def test_supplier_join_uses_supplier_part_plant_and_original_eta(self):
        text = "Acme's widgets for the Alpha line were due Tuesday Mar 9 and arrive Thursday Mar 11."
        incident = normalize_incident({"kind": "supplier_delay", "confirmed": True, "supplier": "Acme", "part": "widgets", "plant": "the Alpha line", "original_eta": "Tuesday Mar 9", "new_eta": "Thursday Mar 11"}, text, self.graph)
        self.assertEqual((incident["shipment_id"], incident["new_eta"]), ("SH-X", "2027-03-11"))

    def test_explicit_shipment_identity_can_supply_missing_metadata(self):
        text = "Shipment SH-X is delayed until Thursday Mar 11."
        incident = normalize_incident({"kind": "supplier_delay", "confirmed": True, "shipment": "SH-X", "new_eta": "Thursday Mar 11"}, text, self.graph)
        self.assertEqual((incident["plant_id"], incident["part_id"], incident["original_eta"]), ("P_A", "PART-X", "2027-03-09"))

    def test_quality_join_uses_lot_build_window(self):
        text = "Quality alert: Acme widgets for the Alpha line are faulty; vehicles built last Thursday through last Friday are suspect."
        incident = normalize_incident({"kind": "quality_hold", "confirmed": True, "supplier": "Acme", "part": "widgets", "plant": "the Alpha line", "start": "last Thursday", "end": "last Friday"}, text, self.graph)
        self.assertEqual(incident["lot_id"], "LOT-X")

    def test_unconfirmed_source_overrides_model_confirmation(self):
        text = "Rumor: P_A might be down next Tuesday through next Thursday."
        incident = normalize_incident({"kind": "plant_outage", "confirmed": True, "plant": "P_A", "start": "next Tuesday", "end": "next Thursday"}, text, self.graph)
        self.assertEqual((incident["kind"], incident["confirmed"]), ("unconfirmed", False))

    def test_noise_remains_noise_when_confirmed_false(self):
        result = normalize_incident({"kind": "noise", "confirmed": False}, "Where is the brochure?", self.graph)
        self.assertEqual(result["kind"], "noise")

    def test_extractor_cannot_supply_tool_actions(self):
        for field in ("actions", "tool", "args"):
            with self.subTest(field=field), self.assertRaises(ExtractionError):
                normalize_incident({"kind": "noise", "confirmed": True, field: "mes.transfer"}, "Read the brochure.", self.graph)

    def test_hallucinated_entity_is_rejected_even_if_id_exists(self):
        with self.assertRaises(ExtractionError):
            normalize_incident({"kind": "plant_outage", "confirmed": True, "plant": "P_B", "start": "next Tuesday", "end": "next Thursday"}, "P_A is down next Tuesday through next Thursday.", self.graph)

    def test_hallucinated_date_is_rejected(self):
        with self.assertRaises(ExtractionError):
            normalize_incident({"kind": "plant_outage", "confirmed": True, "plant": "P_A", "start": "2027-03-17", "end": "2027-03-18"}, "P_A is down next Tuesday through next Thursday.", self.graph)

    def test_model_computed_date_is_only_accepted_if_source_resolves_same(self):
        incident = normalize_incident({"kind": "plant_outage", "confirmed": True, "plant": "P_A", "start": "2027-03-16", "end": "2027-03-18"}, "P_A is down next Tuesday through next Thursday.", self.graph)
        self.assertEqual(incident["start_date"], "2027-03-16")

    def test_invented_evidence_is_rejected(self):
        with self.assertRaises(ExtractionError):
            normalize_incident({"kind": "noise", "confirmed": True, "evidence": "Different source"}, "Where is the brochure?", self.graph)

    def test_confirmation_must_be_boolean_not_string(self):
        incidents = normalize_incidents({"incidents": [{"kind": "noise", "confirmed": "true"}]}, "Brochure?", self.graph)
        self.assertEqual(incidents[0]["kind"], "unconfirmed")

    def test_compound_preserves_valid_incident_while_rejecting_invalid_one(self):
        text = "P_A is down next Tuesday through next Thursday. Shipment SH-X arrives Thursday Mar 11."
        payload = {"incidents": [{"kind": "plant_outage", "confirmed": True, "plant": "P_A", "start": "next Tuesday", "end": "next Thursday", "evidence": "P_A is down next Tuesday through next Thursday."}, {"kind": "supplier_delay", "confirmed": True, "shipment": "SH-X", "new_eta": "2099-01-01", "evidence": "Shipment SH-X arrives Thursday Mar 11."}]}
        incidents = normalize_incidents(payload, text, self.graph)
        self.assertEqual([i["kind"] for i in incidents], ["plant_outage", "unconfirmed"])

    def test_bad_or_empty_payload_fails_closed(self):
        for payload in ({}, [], {"incidents": []}, {"incidents": "noise"}, None):
            with self.subTest(payload=payload):
                self.assertEqual(normalize_incidents(payload, "Something happened.", self.graph)[0]["kind"], "unconfirmed")

    def test_fenced_json_parsed_without_execution(self):
        payload = {"incidents": [{"kind": "noise", "confirmed": False}]}
        self.assertEqual(parse_json_output("```json\n" + json.dumps(payload) + "\n```"), payload)
        with self.assertRaises(ExtractionError):
            parse_json_output("__import__('os').system('echo unsafe')")

    def test_event_parser_injected_output_records_provenance(self):
        parser = EventParser(self.graph, model_path=self.world.path / "not-loaded", revision="unit-test")
        with patch.object(parser, "_generate", return_value=(json.dumps({"incidents": [{"kind": "noise", "confirmed": False}]}), {"input_tokens": 10, "output_tokens": 5, "generation_seconds": 0.0})):
            parsed = parser.parse({"event_id": "SYNTHETIC", "text": "Brochure request."})
        self.assertEqual(parsed["event_id"], "SYNTHETIC")
        self.assertEqual(parsed["incidents"][0]["kind"], "noise")
        self.assertEqual(parsed["provenance"]["revision"], "unit-test")
        self.assertIsNone(parser.model)


if __name__ == "__main__":
    unittest.main()
