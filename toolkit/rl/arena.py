"""Head-to-head evaluation. Win rate with an honest confidence interval.

    python toolkit/rl/arena.py --game duel --a heuristic --b random --games 200
    python toolkit/rl/arena.py --game duel --tournament runs/a/best.zip runs/b/best.zip heuristic mcts:50

Agents swap sides every game. A crash or an illegal move counts as a loss, as it would
with the judge. If two confidence intervals overlap, you haven't shown one is better.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from agents import load_agent
from games import GAMES


def wilson(wins: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def play_game(make_game, agents: dict, seed: int, stats: dict | None = None,
              opening: int = 4) -> dict[int, float]:
    """agents = {player: fn}. Returns {player: result}.

    Starts with `opening` random moves. With a fixed start and deterministic agents,
    every game would otherwise repeat, so 200 games would really be 2 and the confidence
    interval would mean nothing.
    """
    g = make_game()
    g.reset(seed)
    for agent in agents.values():
        if hasattr(agent, "new_game"):
            agent.new_game()
    rng = np.random.default_rng(seed)
    for _ in range(opening):
        if g.is_over():
            break
        g.step({p: int(rng.choice(np.flatnonzero(g.legal_actions(p)))) for p in g.to_move()})
    while not g.is_over():
        joint = {}
        for p in g.to_move():
            start = time.perf_counter()
            try:
                action = agents[p](g, p)
                if not g.legal_actions(p)[action]:
                    raise ValueError(f"illegal action {action}")
            except Exception as e:  # noqa: BLE001 - a broken agent forfeits, it doesn't stop the match
                if stats is not None:
                    stats["crashes"][p] = stats["crashes"].get(p, 0) + 1
                    stats["last_error"] = repr(e)
                return {q: (-1.0 if q == p else 1.0) for q in agents}
            if stats is not None:
                stats["ms"].setdefault(p, []).append((time.perf_counter() - start) * 1000)
            joint[p] = action
        g.step(joint)
    return {p: g.result(p) for p in agents}


def match(make_game, a, b, games: int = 100, seed: int = 0) -> dict:
    wins = draws = losses = 0
    stats = {"ms": {}, "crashes": {}, "last_error": None}
    ms_a: list[float] = []
    crashes_a = 0
    for i in range(games):
        side = i % 2  # a plays player 0 on even games, player 1 on odd
        stats["ms"].clear()
        stats["crashes"].clear()
        res = play_game(make_game, {side: a, 1 - side: b}, seed + i, stats)
        r = res[side]
        wins += r > 0
        draws += r == 0
        losses += r < 0
        ms_a += stats["ms"].get(side, [])
        crashes_a += stats["crashes"].get(side, 0)
    score = wins + 0.5 * draws
    low, high = wilson(score, games)
    return dict(wins=wins, draws=draws, losses=losses, score=score / games, low=low, high=high,
                ms_mean=float(np.mean(ms_a)) if ms_a else 0.0,
                ms_max=float(np.max(ms_a)) if ms_a else 0.0, crashes=crashes_a,
                last_error=stats["last_error"])


def tournament(make_game, specs: list[str], games: int = 50) -> "pd.DataFrame":
    import pandas as pd
    agents = {s: load_agent(s) for s in specs}
    rows = {s: [] for s in specs}
    for i, a in enumerate(specs):
        for b in specs[i + 1:]:
            m = match(make_game, agents[a], agents[b], games)
            print(f"{a} vs {b}: {m['score']:.1%}")
            rows[a].append(m["score"])
            rows[b].append(1 - m["score"])
    table = pd.DataFrame({"agent": specs, "mean_score": [float(np.mean(rows[s])) for s in specs]})
    return table.sort_values("mean_score", ascending=False).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True, choices=sorted(GAMES))
    ap.add_argument("--a")
    ap.add_argument("--b")
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--tournament", nargs="+")
    args = ap.parse_args()
    make_game = GAMES[args.game]
    if args.tournament:
        print(tournament(make_game, args.tournament, args.games).to_string(index=False))
        return
    if not (args.a and args.b):
        sys.exit("Pass --a and --b, or --tournament.")
    m = match(make_game, load_agent(args.a), load_agent(args.b), args.games)
    print(f"{args.a} vs {args.b}, {args.games} games")
    print(f"  W {m['wins']}  D {m['draws']}  L {m['losses']}")
    print(f"  score {m['score']:.1%}  (95% CI {m['low']:.1%} to {m['high']:.1%})")
    print(f"  {args.a}: {m['ms_mean']:.1f} ms mean, {m['ms_max']:.1f} ms worst, {m['crashes']} crashes")
    if m["last_error"]:
        print(f"  last error: {m['last_error']}")


if __name__ == "__main__":
    main()
