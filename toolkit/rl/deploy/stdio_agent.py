"""Agent for judges that run your program and talk over stdin/stdout, one line per turn.

    python toolkit/rl/deploy/stdio_agent.py --game mygame --model policy.pt --fallback heuristic

Same safety as serve.py. Reuses its decode_state and encode_move, so edit those there.
Print only moves to stdout: anything else breaks the protocol, so logs go to stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parents[1])]
from agents import load_agent
from games import GAMES
from serve import SafeAgent, decode_state, encode_move


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--model", default="heuristic")
    ap.add_argument("--fallback", default="heuristic")
    ap.add_argument("--budget-ms", type=float, default=150)
    args = ap.parse_args()
    make_game = GAMES[args.game]
    agent = SafeAgent(load_agent(args.model), load_agent(args.fallback), args.budget_ms)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            game, player = decode_state(make_game, json.loads(line))
            print(json.dumps(encode_move(agent.act(game, player))), flush=True)
        except Exception as e:  # noqa: BLE001 - one bad line must not end the match
            print(f"bad input: {e!r}", file=sys.stderr, flush=True)
            print(json.dumps(encode_move(0)), flush=True)


if __name__ == "__main__":
    main()
