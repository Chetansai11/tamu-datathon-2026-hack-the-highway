"""Ready-to-use clients for the MLH prize APIs, all configured from .env.

    python toolkit/prize_apis.py          status of every service, with live checks
    python toolkit/prize_apis.py --offline   only show which fields are filled in

    from prize_apis import gemini, snowflake, grok
    print(gemini("Summarize this match log: ..."))

Secrets are never printed. Base URLs can be overridden with <NAME>_BASE_URL.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# Nearest .env wins, so one set of keys in the Datathon folder serves all 8 challenges
# and sits outside every git repo.
for _folder in Path(__file__).resolve().parents:
    if (_folder / ".env").exists():
        load_dotenv(_folder / ".env")
TIMEOUT = 30


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def need(*names: str) -> list[str]:
    missing = [n for n in names if not env(n)]
    if missing:
        raise RuntimeError(f"Missing in .env: {', '.join(missing)}")
    return [env(n) for n in names]


def _check(resp: requests.Response) -> dict:
    """Raise a readable error. Never echoes request headers, which hold the key."""
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ---- LLMs --------------------------------------------------------------------

GEMINI_URL = lambda: env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")  # noqa: E731
XAI_URL = lambda: env("XAI_BASE_URL", "https://api.x.ai/v1")  # noqa: E731


def gemini(prompt: str, model: str | None = None) -> str:
    key = need("GEMINI_API_KEY")[0]
    model = model or env("GEMINI_MODEL", "gemini-3.5-flash-lite")
    r = requests.post(f"{GEMINI_URL()}/models/{model}:generateContent",
                      headers={"x-goog-api-key": key},
                      json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]}, timeout=TIMEOUT)
    return _check(r)["candidates"][0]["content"]["parts"][0]["text"]


def snowflake(prompt: str, model: str | None = None, max_tokens: int = 512) -> str:
    url, pat = need("SNOWFLAKE_ACCOUNT_URL", "SNOWFLAKE_PAT")
    r = requests.post(f"{url.rstrip('/')}/api/v2/cortex/v1/chat/completions",
                      headers={"Authorization": f"Bearer {pat}",
                               "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN"},
                      json={"model": model or env("SNOWFLAKE_MODEL", "claude-haiku-4-5"),
                            "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens},
                      timeout=TIMEOUT)
    return _check(r)["choices"][0]["message"]["content"]


def grok(prompt: str, model: str | None = None) -> str:
    key = need("XAI_API_KEY")[0]
    r = requests.post(f"{XAI_URL()}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": model or env("XAI_MODEL", "grok-4.3"),
                            "messages": [{"role": "user", "content": prompt}]}, timeout=TIMEOUT)
    return _check(r)["choices"][0]["message"]["content"]


# ---- Data --------------------------------------------------------------------

def mongo():
    """Returns the configured database, e.g. mongo().matches.insert_one({...})."""
    from pymongo import MongoClient
    client = MongoClient(need("MONGODB_URI")[0], serverSelectionTimeoutMS=8000)
    return client[env("MONGODB_DB", "datathon")]


def tiger():
    """Returns a psycopg connection to Tiger Data (Postgres + TimescaleDB)."""
    import psycopg
    return psycopg.connect(need("TIGER_DATABASE_URL")[0], connect_timeout=10)


def push_training_metrics(csv_path: str, run_name: str) -> int:
    """Load a run's metrics.csv into a Tiger Data hypertable for a live training dashboard."""
    import pandas as pd
    df = pd.read_csv(csv_path)
    with tiger() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS training_metrics (
            time TIMESTAMPTZ NOT NULL DEFAULT now(), run TEXT NOT NULL,
            timesteps BIGINT, minutes DOUBLE PRECISION, score DOUBLE PRECISION)""")
        conn.execute("SELECT create_hypertable('training_metrics', 'time', if_not_exists => TRUE)")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO training_metrics (run, timesteps, minutes, score) VALUES (%s, %s, %s, %s)",
                [(run_name, int(r.timesteps), float(r.minutes), float(r.score)) for r in df.itertuples()])
    return len(df)


# ---- Infrastructure ----------------------------------------------------------

def vultr_account() -> dict:
    key = need("VULTR_API_KEY")[0]
    base = env("VULTR_BASE_URL", "https://api.vultr.com/v2")
    return _check(requests.get(f"{base}/account", headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT))


def solana_rpc(method: str, params: list | None = None):
    url = env("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    if "mainnet" in url:
        raise RuntimeError("Refusing mainnet: this kit is for devnet, where tokens have no real value.")
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        body["params"] = params
    return _check(requests.post(url, json=body, timeout=TIMEOUT)).get("result")


def devto_me() -> dict:
    key = need("DEVTO_API_KEY")[0]
    base = env("DEVTO_BASE_URL", "https://dev.to/api")
    return _check(requests.get(f"{base}/users/me", headers={"api-key": key, "Accept": "application/json"}, timeout=TIMEOUT))


# ---- Status ------------------------------------------------------------------

def _ok_gemini():
    key = need("GEMINI_API_KEY")[0]
    data = _check(requests.get(f"{GEMINI_URL()}/models", headers={"x-goog-api-key": key}, timeout=TIMEOUT))
    return f"{len(data.get('models', []))} models visible"


def _ok_grok():
    key = need("XAI_API_KEY")[0]
    data = _check(requests.get(f"{XAI_URL()}/models", headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT))
    return f"{len(data.get('data', []))} models visible"


def _ok_mongo():
    mongo().client.admin.command("ping")
    return "ping ok"


def _ok_tiger():
    with tiger() as conn:
        conn.execute("SELECT 1")
    return "SELECT 1 ok"


SERVICES = {
    # name: (required fields, live check, prize)
    "Gemini": (["GEMINI_API_KEY"], _ok_gemini, "Best Use of Gemini API"),
    "Snowflake": (["SNOWFLAKE_ACCOUNT_URL", "SNOWFLAKE_PAT"], lambda: snowflake("Reply with: ok", max_tokens=8)[:20], "Best Use of Snowflake API"),
    "Grok (xAI)": (["XAI_API_KEY"], _ok_grok, "SpaceXSI raffle"),
    "Tiger Data": (["TIGER_DATABASE_URL"], _ok_tiger, "Best Use of Tiger Data"),
    "MongoDB": (["MONGODB_URI"], _ok_mongo, "Best Use of MongoDB Atlas"),
    "Vultr": (["VULTR_API_KEY"], lambda: "account ok" if vultr_account() else "", "Best Use of Vultr"),
    "Solana devnet": (["SOLANA_RPC_URL"], lambda: f"getHealth {solana_rpc('getHealth')}", "Best Use of Solana"),
    "DEV": (["DEVTO_API_KEY"], lambda: f"signed in as {devto_me().get('username')}", "DEV Writing Challenge"),
}


def status(live: bool = True) -> list[tuple[str, str, str]]:
    rows = []
    for name, (fields, check, prize) in SERVICES.items():
        missing = [f for f in fields if not env(f)]
        if name == "Solana devnet":
            missing = []  # a default public endpoint works without any field
        if missing:
            state = "NOT SET  " + ", ".join(missing)
        elif not live:
            state = "set"
        else:
            try:
                state = f"OK       {check()}"
            except Exception as e:  # noqa: BLE001 - report it and move on to the next service
                state = f"FAILED   {str(e)[:90]}"
        rows.append((name, state, prize))
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    for name, state, prize in status(not args.offline):
        print(f"{name:14s} {state:<60s} {prize}")
