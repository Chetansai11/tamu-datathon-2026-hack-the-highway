"""Give several models the same time budget, then rank them by playing each other.

    python toolkit/rl/compare.py --game duel --algos mask_ppo,ppo,qrdqn --minutes 20
    python toolkit/rl/compare.py --game gym:Pendulum-v1 --algos sac,tqc,ppo --minutes 10

Extra flags after -- go to every training run, e.g. -- --circular --selfplay
Writes runs/compare_<game>/: leaderboard.csv and a learning-curve chart.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import charts
from games import GAMES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--algos", default="mask_ppo,ppo,qrdqn")
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--eval-every", type=int, default=25_000)
    ap.add_argument("--games", type=int, default=40, help="tournament games per pairing")
    ap.add_argument("extra", nargs=argparse.REMAINDER, help="after --, flags for train.py")
    args = ap.parse_args()
    extra = [x for x in args.extra if x != "--"]

    tag = args.game.replace(":", "_")
    out = Path("runs") / f"compare_{tag}"
    out.mkdir(parents=True, exist_ok=True)
    curves, runs = [], {}
    for algo in args.algos.split(","):
        name = f"cmp_{tag}_{algo}"
        print(f"\n=== {algo} for {args.minutes} min ===", flush=True)
        code = subprocess.call([sys.executable, str(HERE / "train.py"), "--game", args.game, "--algo", algo,
                                "--name", name, "--minutes", str(args.minutes),
                                "--eval-every", str(args.eval_every), *extra])
        metrics = Path("runs") / name / "metrics.csv"
        if code != 0 or not metrics.exists():
            print(f"{algo} failed (exit {code}), skipping it.")
            continue
        runs[algo] = str(Path("runs") / name / "best.zip")
        curves.append(pd.read_csv(metrics).assign(algo=algo))

    if not curves:
        sys.exit("No run finished.")
    data = pd.concat(curves)
    data.to_csv(out / "curves.csv", index=False)
    summary = data.groupby("algo").agg(best_score=("score", "max"), steps=("timesteps", "max")).sort_values("best_score", ascending=False)

    if args.game in GAMES and len(runs) > 1:
        from arena import tournament
        table = tournament(GAMES[args.game], [*runs.values(), "heuristic"], args.games)
        names = {v: k for k, v in runs.items()}
        table["agent"] = table["agent"].map(lambda a: names.get(a, a))
        print("\nTournament:\n" + table.to_string(index=False))
        summary = summary.join(table.set_index("agent")["mean_score"].rename("tournament")).sort_values("tournament", ascending=False)

    print("\nLeaderboard:\n" + summary.to_string())
    summary.to_csv(out / "leaderboard.csv")
    charts.setup()
    fig, _ = charts.lines(data, "minutes", "score", f"Best so far: {summary.index[0]}", series="algo",
                          subtitle="Arena score during training, same time budget", ylabel="score")
    print("Chart:", charts.save(fig, "learning_curves", out))


if __name__ == "__main__":
    main()
