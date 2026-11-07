"""Model-free parser guardrails over generated company data and injected outputs."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.parse import EventParser, ExtractionError, _gemini_request, discover_gemini_model, normalize_incident, normalize_incidents, parse_json_output, resolve_date

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

    def test_gemini_catalog_paginates_and_prefers_stable_supported_flash_lite(self):
        catalog = [
            {"models": [{"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/gemini-9-flash-lite-preview", "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "page-two"},
            {"models": [{"name": "models/gemini-3.5-flash-lite", "version": "fixture-version", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/gemini-8-flash-lite", "supportedGenerationMethods": ["embedContent"]}, {"name": "models/gemini-9-pro", "supportedGenerationMethods": ["generateContent"]}]},
        ]
        with patch("src.parse.gemini_key_configured", return_value=True), patch("src.parse._gemini_request", side_effect=catalog) as request:
            selected = discover_gemini_model()
        self.assertEqual(selected["model"], "gemini-3.5-flash-lite")
        self.assertEqual(selected["version"], "fixture-version")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].kwargs["params"]["pageToken"], "page-two")

    def test_gemini_explicit_model_must_be_catalog_supported(self):
        catalog = {"models": [{"name": "models/gemini-fixture", "supportedGenerationMethods": ["generateContent"]}]}
        with patch("src.parse.gemini_key_configured", return_value=True), patch("src.parse._gemini_request", return_value=catalog):
            self.assertEqual(discover_gemini_model("models/gemini-fixture")["model"], "gemini-fixture")
            with self.assertRaises(RuntimeError):
                discover_gemini_model("gemini-does-not-exist")

    def test_gemini_missing_key_stops_before_network_request(self):
        with patch("src.parse.gemini_key_configured", return_value=False), patch("requests.request") as request:
            for call in (lambda: discover_gemini_model(), lambda: _gemini_request("GET", "models")):
                with self.subTest(call=call), self.assertRaisesRegex(RuntimeError, "not configured"):
                    call()
            request.assert_not_called()

    def test_gemini_errors_do_not_expose_key_url_headers_or_response_body(self):
        import requests
        fake_key = "UNIT-TEST-SECRET-DO-NOT-ECHO"
        fake_host = "https://unit-test-private-host.invalid/v1beta"
        cases = [
            requests.ConnectionError(f"Failed {fake_host} x-goog-api-key={fake_key}"),
            SimpleNamespace(ok=False, status_code=403, text=f"Rejected key {fake_key}"),
        ]
        with patch("src.parse.gemini_key_configured", return_value=True), patch("toolkit.prize_apis.need", return_value=[fake_key]), patch("toolkit.prize_apis.GEMINI_URL", return_value=fake_host):
            for result in cases:
                with self.subTest(result=type(result).__name__):
                    request_kwargs = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                    with patch("requests.request", **request_kwargs) as request, self.assertRaises(RuntimeError) as caught:
                        _gemini_request("POST", "models/unit-test:generateContent", body={"test": True})
                    message = str(caught.exception)
                    self.assertNotIn(fake_key, message)
                    self.assertNotIn(fake_host, message)
                    self.assertNotIn("x-goog-api-key", message)
                    self.assertNotIn(fake_key, request.call_args.args[1])
                    self.assertEqual(request.call_args.kwargs["headers"]["x-goog-api-key"], fake_key)

    def test_gemini_generation_preserves_model_version_and_token_provenance(self):
        parser = EventParser(self.graph, provider="gemini", max_new_tokens=2048)
        raw = json.dumps({"incidents": [{"kind": "noise", "confirmed": False}]})
        payload = {"modelVersion": "gemini-fixture-resolved-2027", "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Internal thought must be excluded", "thought": True}, {"text": raw}]}}], "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 24, "totalTokenCount": 144, "thoughtsTokenCount": 20}}
        with patch("src.parse.discover_gemini_model", return_value={"model": "gemini-3.5-flash-lite", "version": "catalog-version"}) as catalog, patch("src.parse._gemini_request", return_value=payload) as request:
            parsed = parser.parse({"event_id": "SYNTHETIC", "text": "Brochure request."})
        catalog.assert_called_once()
        provenance = parsed["provenance"]
        self.assertEqual(provenance["revision"], "gemini-fixture-resolved-2027")
        self.assertEqual(provenance["model"], "gemini-3.5-flash-lite")
        self.assertEqual([provenance[k] for k in ("input_tokens", "output_tokens", "total_tokens", "thinking_tokens")], [100, 24, 144, 20])
        self.assertEqual(provenance["raw_output"], raw)
        self.assertEqual(provenance["finish_reason"], "STOP")
        self.assertEqual(request.call_args.kwargs["body"]["generationConfig"]["maxOutputTokens"], 2048)
        self.assertEqual(parsed["incidents"][0]["kind"], "noise")

    def test_gemini_incomplete_or_blocked_generation_cannot_be_accepted(self):
        raw = json.dumps({"incidents": [{"kind": "noise", "confirmed": False}]})
        payloads = [{"candidates": []}, {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": raw}]}}]}, {"candidates": [{"finishReason": "SAFETY", "content": {"parts": [{"text": raw}]}}]}]
        for payload in payloads:
            with self.subTest(payload=payload):
                parser = EventParser(self.graph, provider="gemini")
                with patch("src.parse.discover_gemini_model", return_value={"model": "gemini-3.5-flash-lite"}), patch("src.parse._gemini_request", return_value=payload), self.assertRaises(RuntimeError):
                    parser.parse({"event_id": "SYNTHETIC", "text": "Brochure request."})


if __name__ == "__main__":
    unittest.main()
