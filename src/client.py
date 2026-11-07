"""Validated HTTP adapter for the official local enterprise server.

Only reads retry. A timed-out write has an unknown outcome and must be checked
against the server action log before an operator starts a fresh run.
"""
from __future__ import annotations

import copy
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


READ_TOOLS = frozenset({"mes.get_schedule", "crm.loaner_availability"})
FIRST_DAY = date(2027, 3, 8)
LAST_DAY = date(2027, 4, 2)


class ClientError(RuntimeError):
    """Base exception for explicit caller handling."""


class ValidationError(ClientError, ValueError):
    """Rejected locally before making a server call."""


class ToolCallError(ClientError):
    """The server rejected a request and reported the reason."""


class UnknownOutcomeError(ClientError):
    """A side-effecting call may have succeeded. Never automatically retry it."""


class EnterpriseClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8606", log_path=None,
                 timeout: float = 10.0, read_retries: int = 2):
        url = urlparse(base_url)
        if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username or url.password or url.query or url.fragment
                or url.path not in {"", "/"}):
            raise ValidationError("Enterprise URL must be a local HTTP origin")
        if timeout <= 0 or not isinstance(read_retries, int) or read_retries < 0:
            raise ValidationError("timeout must be positive and read_retries a nonnegative integer")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.read_retries = read_retries
        self.log_path = Path(log_path) if log_path is not None else None
        self.history: list[dict[str, Any]] = []
        self._tools: dict[str, dict] | None = None
        self._events: list[dict] | None = None

    def _request(self, path: str, body=None, *, retry: bool = False):
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + path, data=payload,
                          headers={"Content-Type": "application/json"},
                          method="GET" if body is None else "POST")
        for attempt in range(1 + (self.read_retries if retry else 0)):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                # Official 4xx responses describe a rejected call, not an unknown write.
                try:
                    detail = json.loads(exc.read().decode("utf-8")).get("error", str(exc.code))
                except (ValueError, UnicodeError, AttributeError):
                    detail = f"HTTP {exc.code}"
                if exc.code < 500:
                    raise ToolCallError(str(detail)) from None
                if retry and attempt < self.read_retries:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                cls = ClientError if retry or body is None else UnknownOutcomeError
                raise cls(f"HTTP {exc.code}: {detail}") from None
            except (URLError, TimeoutError, ConnectionError, OSError, ValueError) as exc:
                if retry and attempt < self.read_retries:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                cls = ClientError if retry or body is None else UnknownOutcomeError
                raise cls(f"Transport/response failure: {type(exc).__name__}") from None

    def tools(self, refresh: bool = False) -> list[dict]:
        if self._tools is None or refresh:
            rows = self._request("/tools", retry=True)
            if not isinstance(rows, list) or not rows:
                raise ClientError("Invalid /tools response")
            if not all(isinstance(r, dict) and isinstance(r.get("tool"), str)
                       and isinstance(r.get("args"), dict) for r in rows):
                raise ClientError("Invalid tool schema")
            self._tools = {r["tool"]: r for r in rows}
        return copy.deepcopy(list(self._tools.values()))

    def events(self, refresh: bool = False) -> list[dict]:
        if self._events is None or refresh:
            rows = self._request("/events", retry=True)
            if not isinstance(rows, list) or not all(
                isinstance(r, dict) and isinstance(r.get("event_id"), str) for r in rows
            ):
                raise ClientError("Invalid /events response")
            self._events = rows
        return copy.deepcopy(self._events)

    def _validate(self, event_id: str, tool: str, args: dict):
        self.tools()
        self.events()
        if not isinstance(event_id, str) or event_id not in {r["event_id"] for r in self._events}:
            raise ValidationError("Unknown event_id")
        if not isinstance(tool, str) or tool not in self._tools:
            raise ValidationError("Unknown tool")
        if not isinstance(args, dict):
            raise ValidationError("args must be an object")
        schema = self._tools[tool]["args"]
        if set(args) != set(schema):
            raise ValidationError(f"Arguments must exactly match {sorted(schema)}")
        for name, kind in schema.items():
            value = args[name]
            if kind in {"str", "YYYY-MM-DD"}:
                if not isinstance(value, str) or not value.strip():
                    raise ValidationError(f"{name} must be a nonempty string")
                if kind == "YYYY-MM-DD":
                    try:
                        parsed = date.fromisoformat(value)
                    except ValueError:
                        raise ValidationError(f"{name} must be YYYY-MM-DD") from None
                    if parsed.isoformat() != value or parsed.weekday() >= 5 or not FIRST_DAY <= parsed <= LAST_DAY:
                        raise ValidationError(f"{name} must be a weekday from {FIRST_DAY} through {LAST_DAY}")
            elif kind == "list[str]":
                if (not isinstance(value, list) or not value
                        or not all(isinstance(v, str) and v.strip() for v in value)):
                    raise ValidationError(f"{name} must be a nonempty list of nonempty strings")
                if len(set(value)) != len(value):
                    raise ValidationError(f"{name} must not contain duplicates")
            else:
                raise ValidationError(f"Unsupported argument schema: {kind}")

    def _audit(self, entry: dict):
        self.history.append(entry)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def act(self, event_id: str, tool: str, args: dict) -> dict:
        """Validate, call once for writes, audit the result, and raise on failure."""
        started = time.perf_counter()
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event_id": event_id,
                 "tool": tool, "args": copy.deepcopy(args), "sent": False}
        try:
            self._validate(event_id, tool, args)
            entry["sent"] = True
            result = self._request("/act", {"event_id": event_id, "tool": tool, "args": args},
                                   retry=tool in READ_TOOLS)
            if not isinstance(result, dict):
                cls = ClientError if tool in READ_TOOLS else UnknownOutcomeError
                raise cls("Invalid action response")
            if "error" in result or result.get("ok") is False:
                raise ToolCallError(str(result.get("error", "Action was rejected")))
            if tool not in READ_TOOLS and result.get('ok') is not True:
                raise UnknownOutcomeError('Action response did not explicitly confirm success')
            entry.update(ok=True, outcome="confirmed", result=result)
            return result
        except Exception as exc:
            entry.update(ok=False, error=str(exc), error_type=type(exc).__name__,
                         outcome="unknown" if isinstance(exc, UnknownOutcomeError) else "rejected")
            raise
        finally:
            entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            self._audit(entry)


def export_tool_documentation(client: EnterpriseClient, output_path) -> None:
    """Write the live GET /tools contract, including every argument."""
    rows = client.tools(refresh=True)
    lines = ["# Enterprise tool contract", "", "Fetched from the official local server's `GET /tools`.",
             "", "Every call: `POST /act` with `event_id`, `tool`, and `args`.",
             "Each event has an independent fresh world. Compound incidents share that event's world.",
             "", "| Tool | Arguments | Behavior |", "| --- | --- | --- |"]
    for row in rows:
        arguments = "; ".join(f"`{name}: {kind}`" for name, kind in row["args"].items())
        lines.append(f"| `{row['tool']}` | {arguments} | {row['desc']} |")
    lines += ["", "## Client safeguards", "",
              "`EnterpriseClient` accepts only a local HTTP origin, known event ids and tool names, exact argument keys, nonempty strings and lists, and unique list entries. Tool dates must be canonical ISO weekdays from 2027-03-08 through 2027-04-02.",
              "", "Only `mes.get_schedule` and `crm.loaner_availability` may retry automatically. Operational writes and `escalate` are never retried. A connection failure or malformed response after a write raises `UnknownOutcomeError`; inspect the authoritative server log before restarting. HTTP 4xx tool rejection raises `ToolCallError`.",
              "", "Client validation does not decide operational policy. The policy layer must read schedules/pools before writes and validate affected entities against the graph and tables. `escalate` is classified as non-operational by the official server but still changes escalation state.",
              "", "The official `runs/<run>/action_log.jsonl` is the submission log. The optional client audit log also records responses, locally rejected requests, timings and unknown outcomes; it is separate from the official log.", ""]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
