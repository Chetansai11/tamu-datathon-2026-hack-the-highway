"""Run this on every new Game before training. A wrong plug-in wastes hours of training.

    python toolkit/rl/check_game.py mygame
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from games import GAMES


def check(make_game, games: int = 300, max_steps: int = 20_000) -> list[str]:
    errors: list[str] = []

    def err(msg):
        if msg not in errors:
            errors.append(msg)

    g = make_game()
    if not getattr(g, "num_actions", 0):
        return ["num_actions is not set"]
    if not getattr(g, "obs_shape", None):
        return ["obs_shape is not set"]

    rng = np.random.default_rng(0)
    lengths, results = [], []
    moves = 0
    start = time.perf_counter()
    for i in range(games):
        g = make_game()
        g.reset(i)
        steps = 0
        while not g.is_over():
            steps += 1
            if steps > max_steps:
                err(f"game {i} didn't end within {max_steps} steps: is_over() may never be true")
                break
            joint = {}
            players = g.to_move()
            if not players:
                err("to_move() returned no players while the game is live")
                break
            if g.simultaneous and len(players) != g.num_players:
                err("simultaneous=True, but to_move() doesn't list every player")
            for p in players:
                mask = g.legal_actions(p)
                if mask.shape != (g.num_actions,):
                    err(f"legal_actions shape {mask.shape}, expected ({g.num_actions},)")
                if mask.dtype != bool:
                    err(f"legal_actions dtype is {mask.dtype}, it must be bool")
                if not mask.any():
                    err("legal_actions is all False on a live game: this crashes MaskablePPO")
                    break
                obs = g.observe(p)
                if tuple(obs.shape) != tuple(g.obs_shape):
                    err(f"observe shape {obs.shape}, expected {g.obs_shape}")
                if not np.isfinite(obs).all():
                    err("observe contains NaN or inf")
                if obs.min() < g.obs_low or obs.max() > g.obs_high:
                    err(f"observe range {obs.min()} to {obs.max()} is outside obs_low/obs_high")
                before = obs.copy()
                if not np.array_equal(g.observe(p), before):
                    err("observe isn't repeatable, or legal_actions changes game state")
                joint[p] = int(rng.choice(np.flatnonzero(mask)))
            if errors and "all False" in errors[-1]:
                break
            if i < 20 and steps % 5 == 1 and getattr(g, "supports_clone", True):  # must be independent
                c = g.clone()
                probe = {p: joint[p] for p in joint}
                before = [g.observe(p).copy() for p in range(g.num_players)]
                c.step(probe)
                after = [g.observe(p) for p in range(g.num_players)]
                if any(not np.array_equal(x, y) for x, y in zip(before, after)):
                    err("clone() shares state with the original: search will corrupt the game")
            g.step(joint)
            moves += 1
        else:
            r = [g.result(p) for p in range(g.num_players)]
            results.append(r)
            lengths.append(steps)
            if any(abs(x) > 1 for x in r):
                err(f"result() outside [-1, 1]: {r}")
            if g.num_players == 2 and abs(r[0] + r[1]) > 1e-9:
                err(f"results don't sum to zero: {r}. Is one player scored wrongly?")
        if len(errors) > 8:
            break

    elapsed = time.perf_counter() - start
    if lengths:
        wins0 = np.mean([r[0] > 0 for r in results])
        wins1 = np.mean([r[1] > 0 for r in results])
        print(f"Played {len(lengths)} random games: {np.mean(lengths):.1f} steps on average "
              f"(max {max(lengths)}), {moves / elapsed:,.0f} steps/sec")
        print(f"Random play: P0 wins {wins0:.1%}, P1 wins {wins1:.1%}, draws {1 - wins0 - wins1:.1%}")
        if moves / elapsed < 2000:
            print("Slow game: under 2k steps/sec means RL gets very few games. Profile step() and observe().")
        if max(wins0, wins1) > 0.75:
            print("Warning: a big first-player edge. Check the rules, and always evaluate on both sides.")

    p0, p1 = make_game(), make_game()
    p0.reset(123)
    p1.reset(123)
    if not np.array_equal(p0.observe(0), p1.observe(0)):
        print("Note: reset(seed) isn't deterministic. Replays and tests won't reproduce.")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("game", choices=sorted(GAMES))
    ap.add_argument("--games", type=int, default=300)
    args = ap.parse_args()
    make_game = GAMES[args.game]
    errors = check(make_game, args.games)
    if not errors:
        from stable_baselines3.common.env_checker import check_env
        from envs import GameEnv
        env = GameEnv(make_game, "random")
        check_env(env, warn=False)
        print("Gym env check passed.")
    if errors:
        print(f"\nFAILED with {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("\nAll checks passed. Safe to train.")


if __name__ == "__main__":
    main()
