"""Crash-proof agent server for a judge that calls your bot over HTTP.

    python toolkit/rl/deploy/serve.py --game duel --model runs/x/policy.pt --budget-ms 150

Match the routes and JSON to the challenge: edit ROUTES, decode_state and encode_move.
Defaults follow the 2025 Case Closed API, as a starting point only.

A move always goes out in time. The trained model gets a deadline; on a timeout or
any error, the fallback plays instead. Losing to a crash is the worst way to lose.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Timeout
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).parents[1]))
from agents import load_agent
from games import GAMES

ROUTES = dict(info="/", state="/send-state", move="/send-move", end="/end")
PARTICIPANT, AGENT_NAME = "YourTeam", "YourAgent"


def decode_state(make_game, data: dict):
    """TODO: rebuild a Game from the judge's JSON. Return (game, my_player)."""
    if "demo_seed" in data:  # lets the kit's smoke test run without a real judge
        game = make_game()
        game.reset(data["demo_seed"])
        return game, int(data.get("player", 0))
    raise NotImplementedError("Write decode_state for this challenge's JSON.")


def log_exchange(data: dict, reply: dict) -> None:
    """With REPLAY_LOG set, keep every judge exchange. This is your training data if
    their engine is hidden, and the proof of what really happened in a lost match."""
    path = os.getenv("REPLAY_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"state": data, "reply": reply}) + "\n")


def encode_move(action: int) -> dict:
    """TODO: convert an action index to the judge's format, e.g. "UP:BOOST"."""
    return {"move": int(action)}


class SafeAgent:
    def __init__(self, primary, fallback, budget_ms: float):
        self.primary, self.fallback, self.budget = primary, fallback, budget_ms / 1000
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.stats = dict(moves=0, timeouts=0, errors=0)

    def act(self, game, player: int) -> int:
        self.stats["moves"] += 1
        future = self.pool.submit(self.primary, game.clone(), player)
        try:
            action = int(future.result(timeout=self.budget))
            if game.legal_actions(player)[action]:
                return action
            self.stats["errors"] += 1
        except Timeout:
            self.stats["timeouts"] += 1
            # Replace the worker that's stuck, so the next move isn't queued behind it.
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = ThreadPoolExecutor(max_workers=2)
        except Exception as e:  # noqa: BLE001 - any failure must still produce a move
            self.stats["errors"] += 1
            print("primary failed:", repr(e), file=sys.stderr, flush=True)
        try:
            return int(self.fallback(game, player))
        except Exception:  # noqa: BLE001
            return int(np.flatnonzero(game.legal_actions(player))[0])


def create_app(game_name: str, model: str, fallback: str, budget_ms: float) -> Flask:
    app = Flask(__name__)
    make_game = GAMES[game_name]
    agent = SafeAgent(load_agent(model), load_agent(fallback), budget_ms)
    latest: dict = {}
    # The first calls are the slowest (TorchScript optimizes on them), so spend them here.
    warm = make_game()
    warm.reset(0)
    for _ in range(3):
        agent.primary(warm.clone(), warm.to_move()[0])

    @app.get(ROUTES["info"])
    def info():
        return jsonify(participant=PARTICIPANT, agent_name=AGENT_NAME)

    @app.post(ROUTES["state"])
    def state():
        latest.clear()
        latest.update(request.get_json(force=True))
        return jsonify(status="ok")

    @app.get(ROUTES["move"])
    def move():
        start = time.perf_counter()
        game, player = decode_state(make_game, latest)
        reply = encode_move(agent.act(game, player))
        log_exchange(latest, reply)
        print(f"move {reply} in {(time.perf_counter() - start) * 1000:.1f} ms", flush=True)
        return jsonify(reply)

    @app.post(ROUTES["end"])
    def end():
        print("game over", agent.stats, flush=True)
        return jsonify(status="ok")

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default=os.getenv("GAME", "duel"))
    ap.add_argument("--model", default=os.getenv("MODEL", "heuristic"))
    ap.add_argument("--fallback", default=os.getenv("FALLBACK", "heuristic"))
    ap.add_argument("--budget-ms", type=float, default=float(os.getenv("BUDGET_MS", "150")))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    args = ap.parse_args()
    create_app(args.game, args.model, args.fallback, args.budget_ms).run(
        host="0.0.0.0", port=args.port, threaded=True)
