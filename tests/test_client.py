"""HTTP adapter validation, error semantics and retry limits without network calls."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.client import ClientError, EnterpriseClient, ToolCallError, UnknownOutcomeError, ValidationError

try:
    from tests.fixtures import enterprise
except ModuleNotFoundError:
    from fixtures import enterprise


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()


class ClientGuardrailsTest(unittest.TestCase):
    def setUp(self):
        self.client = EnterpriseClient(read_retries=2)
        self.client._tools = {tool: {"tool": tool, "args": definition["args"], "desc": definition["desc"]} for tool, definition in enterprise.TOOLS.items()}
        self.client._events = [{"event_id": "TEST"}]

    def test_rejects_nonlocal_origins_credentials_and_extra_paths(self):
        for url in ("https://127.0.0.1:8000", "http://example.test", "http://127.0.0.1:8000/act", "http://user@localhost:8000", "http://localhost:8000?key=value"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                EnterpriseClient(url)

    def test_bad_event_or_tool_is_not_sent(self):
        with patch("src.client.urlopen") as request:
            for event, tool in (("UNKNOWN", "escalate"), ("TEST", "unknown.tool")):
                with self.subTest(event=event, tool=tool), self.assertRaises(ValidationError):
                    self.client.act(event, tool, {"reason": "test"})
            request.assert_not_called()
        self.assertTrue(all(not record["sent"] for record in self.client.history))

    def test_missing_extra_or_invalid_argument_is_rejected_locally(self):
        invalid = [{}, {"reason": "x", "extra": True}, {"reason": " "}, {"reason": 1}, []]
        with patch("src.client.urlopen") as request:
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(ValidationError):
                    self.client.act("TEST", "escalate", args)
            request.assert_not_called()

    def test_dates_require_canonical_weekday_in_planning_window(self):
        for day in ("2027-03-07", "2027-03-13", "2027-04-05", "20270309", "bad-date"):
            with self.subTest(day=day), patch("src.client.urlopen") as request, self.assertRaises(ValidationError):
                self.client.act("TEST", "mes.reschedule", {"production_order_id": "A", "new_date": day})
            request.assert_not_called()

    def test_duplicate_or_empty_lists_rejected(self):
        for ids in ([], ["CO1", "CO1"], [""], [1], "CO1"):
            with self.subTest(ids=ids), patch("src.client.urlopen") as request, self.assertRaises(ValidationError):
                self.client.act("TEST", "dealer.notify", {"dealer_id": "D1", "customer_order_ids": ids, "message": "delay"})
            request.assert_not_called()

    def test_successful_write_has_confirmed_audit_record(self):
        with patch("src.client.urlopen", return_value=Response({"ok": True})) as request:
            self.assertEqual(self.client.act("TEST", "escalate", {"reason": "unclear"}), {"ok": True})
        request.assert_called_once()
        self.assertEqual(self.client.history[-1]["outcome"], "confirmed")

    def test_write_timeout_is_never_retried_and_outcome_unknown(self):
        with patch("src.client.urlopen", side_effect=TimeoutError) as request, self.assertRaises(UnknownOutcomeError):
            self.client.act("TEST", "mes.reschedule", {"production_order_id": "A", "new_date": "2027-03-10"})
        request.assert_called_once()
        self.assertEqual(self.client.history[-1]["outcome"], "unknown")

    def test_escalation_timeout_is_not_retried(self):
        with patch("src.client.urlopen", side_effect=URLError("connection lost")) as request, self.assertRaises(UnknownOutcomeError):
            self.client.act("TEST", "escalate", {"reason": "unclear"})
        request.assert_called_once()

    def test_read_transport_failures_retry_up_to_bound(self):
        with patch("src.client.urlopen", side_effect=[TimeoutError(), TimeoutError(), Response({"dealer_id": "D1", "available": 1})]) as request, patch("src.client.time.sleep"):
            self.assertEqual(self.client.act("TEST", "crm.loaner_availability", {"dealer_id": "D1"})["available"], 1)
        self.assertEqual(request.call_count, 3)

    def test_failed_read_exhausts_retries(self):
        with patch("src.client.urlopen", side_effect=TimeoutError) as request, patch("src.client.time.sleep"), self.assertRaises(ClientError):
            self.client.act("TEST", "crm.loaner_availability", {"dealer_id": "D1"})
        self.assertEqual(request.call_count, 3)

    def test_server_4xx_is_rejected_without_retry(self):
        rejection = HTTPError("http://localhost/act", 400, "bad", None, io.BytesIO(b'{"error":"no free slot"}'))
        with patch("src.client.urlopen", side_effect=rejection) as request, self.assertRaises(ToolCallError):
            self.client.act("TEST", "mes.reschedule", {"production_order_id": "A", "new_date": "2027-03-10"})
        request.assert_called_once()
        self.assertEqual(self.client.history[-1]["outcome"], "rejected")

    def test_server_5xx_write_outcome_unknown_without_retry(self):
        failure = HTTPError("http://localhost/act", 500, "bad", None, io.BytesIO(b'{"error":"server error"}'))
        with patch("src.client.urlopen", side_effect=failure) as request, self.assertRaises(UnknownOutcomeError):
            self.client.act("TEST", "mes.reschedule", {"production_order_id": "A", "new_date": "2027-03-10"})
        request.assert_called_once()

    def test_response_without_write_confirmation_is_unknown(self):
        with patch("src.client.urlopen", return_value=Response({})) as request, self.assertRaises(UnknownOutcomeError):
            self.client.act("TEST", "mes.reschedule", {"production_order_id": "A", "new_date": "2027-03-10"})
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
