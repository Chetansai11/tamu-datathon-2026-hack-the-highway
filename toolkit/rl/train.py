"""Train any model on any plugged-in game.

    python toolkit/rl/train.py --game duel --algo mask_ppo --minutes 30 --selfplay
    python toolkit/rl/train.py --game duel --algo mask_ppo --circular --bc-games 500 --selfplay
    python toolkit/rl/train.py --game connect4 --algo qrdqn --opponent random@1,heuristic@2
    python toolkit/rl/train.py --game gym:Pendulum-v1 --algo sac --minutes 10
    python toolkit/rl/train.py --game duel --algo mask_ppo --resume runs/x/last.zip --selfplay

Writes runs/<name>/: best.zip (top arena score), last.zip, checkpoints, metrics.csv.
Ctrl+C is safe: it saves last.zip first. Use --subproc when the game is slow.
"""
from __future__ import annotations

import argparse
import csv
import functools
import sys
import time
from pathlib import Path

import gymnasium as gym
import numpy as np
import torch
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv, VecFrameStack, VecNormalize

sys.path.insert(0, str(Path(__file__).parent))
from agents import PolicyAgent, load_agent
from arena import match
from envs import GameEnv
from games import GAMES, GYM_GAMES
from models import ALGOS, build_model, load_model, parse_overrides, write_run_info


def _game_env(make_game, opponent, pool_dir, seed):
    env = Monitor(GameEnv(make_game, opponent, pool_dir), info_keywords=("result",))
    env.reset(seed=seed)
    return env


def _gym_env(game: str, seed: int):
    env = gym.make(game[4:]) if game.startswith("gym:") else GYM_GAMES[game]()
    env = Monitor(env)
    env.reset(seed=seed)
    return env


class Trainer(BaseCallback):
    """Evaluates, snapshots for self-play, keeps the best model and enforces the time limit."""

    def __init__(self, args, run: Path, make_game=None):
        super().__init__()
        self.args, self.run, self.make_game = args, run, make_game
        self.next_eval = args.eval_every
        self.best = -np.inf
        self.start = time.time()
        self.csv_path = run / "metrics.csv"
        self.benchmarks = [b.strip() for b in args.benchmarks.split(",")]
        self.agents = {b: load_agent(b) for b in self.benchmarks} if make_game else {}
        self.snapshots = 0

    def _save(self, name: str) -> None:
        self.model.save(self.run / name)
        vec = self.model.get_vec_normalize_env()
        if vec is not None:
            vec.save(str(self.run / f"{Path(name).stem}_vecnormalize.pkl"))

    def _on_training_start(self) -> None:
        with self.csv_path.open("w", newline="") as f:
            head = self.benchmarks if self.make_game else ["mean_return"]
            csv.writer(f).writerow(["timesteps", "minutes", *head, "score"])

    def _evaluate(self) -> None:
        row: list = []
        if self.make_game:
            me = PolicyAgent(model=self.model, algo=self.args.algo)
            scores = []
            for name, opp in self.agents.items():
                m = match(self.make_game, me, opp, self.args.eval_games)
                scores.append(m["score"])
                row.append(round(m["score"], 4))
            score = float(np.mean(scores))
        else:
            buf = self.model.ep_info_buffer
            score = float(np.mean([e["r"] for e in buf])) if buf else -np.inf
            row.append(round(score, 3))
        minutes = (time.time() - self.start) / 60
        with self.csv_path.open("a", newline="") as f:
            csv.writer(f).writerow([self.num_timesteps, round(minutes, 2), *row, round(score, 4)])
        fps = self.num_timesteps / max(time.time() - self.start, 1e-6)
        print(f"[{minutes:6.1f}m] {self.num_timesteps:>10,} steps ({fps:,.0f}/s)  score {score:.3f}  {row}", flush=True)
        if score > self.best:
            self.best = score
            self._save("best.zip")
        if self.args.selfplay and (not self.make_game or score >= self.args.snapshot_gate):
            self.snapshots += 1
            self.model.save(self.run / "pool" / f"snap_{self.num_timesteps:010d}.zip")
            snaps = sorted((self.run / "pool").glob("snap_*.zip"))
            for old in snaps[:-self.args.pool_size]:
                old.unlink()

    def _on_step(self) -> bool:
        if self.num_timesteps >= self.next_eval:
            self.next_eval += self.args.eval_every
            self._evaluate()
            self._save("last.zip")
        return not (self.args.minutes and (time.time() - self.start) / 60 >= self.args.minutes)


def behaviour_clone(model, make_game, algo: str, games: int, epochs: int = 6, explore: float = 0.1) -> None:
    """Warm start: teach the policy the hand-written heuristic before RL begins.

    A policy that starts near your heuristic skips hours of random flailing.
    """
    if algo not in ("mask_ppo", "ppo"):
        print(f"Skipping BC: it supports mask_ppo and ppo, not {algo}.")
        return
    obs, acts, masks = [], [], []
    for i in range(games):
        g = make_game()
        g.reset(10_000 + i)
        while not g.is_over():
            joint = {}
            for p in g.to_move():
                mask = g.legal_actions(p)
                teacher = g.heuristic(p)
                obs.append(g.observe(p).astype(np.float32))
                acts.append(teacher)
                masks.append(mask)
                # Random moves show the teacher more varied positions.
                joint[p] = int(np.random.choice(np.flatnonzero(mask))) if np.random.random() < explore else teacher
            g.step(joint)
    device = model.device
    X = torch.as_tensor(np.array(obs), device=device)
    y = torch.as_tensor(np.array(acts), device=device)
    M = torch.as_tensor(np.array(masks), device=device)
    opt = torch.optim.Adam(model.policy.parameters(), lr=1e-3)
    n = len(y)
    print(f"BC: {n:,} teacher moves from {games} games")
    for epoch in range(epochs):
        idx = torch.randperm(n, device=device)
        total, correct = 0.0, 0
        for start in range(0, n, 512):
            b = idx[start:start + 512]
            if algo == "mask_ppo":
                dist = model.policy.get_distribution(X[b], action_masks=M[b].cpu().numpy())
            else:
                dist = model.policy.get_distribution(X[b])
            loss = -dist.log_prob(y[b]).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item() * len(b)
            correct += (dist.mode() == y[b]).sum().item()
        print(f"  epoch {epoch + 1}: loss {total / n:.3f}, matches teacher {correct / n:.1%}")


def main() -> None:
    ap = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--game", required=True, help="name in games/__init__.py, or gym:Env-v1")
    ap.add_argument("--algo", default="mask_ppo", choices=sorted(ALGOS))
    ap.add_argument("--name", help="run folder name")
    ap.add_argument("--steps", type=int, default=100_000_000, help="max env steps")
    ap.add_argument("--minutes", type=float, default=0, help="stop after this long")
    ap.add_argument("--n-envs", type=int, default=0, help="0 chooses for the algorithm")
    ap.add_argument("--subproc", action="store_true", help="one process per env (for slow games)")
    ap.add_argument("--opponent", default="random@1,heuristic@2", help="training mix: name@weight")
    ap.add_argument("--selfplay", action="store_true", help="add past snapshots to the opponents")
    ap.add_argument("--snapshot-gate", type=float, default=0.55, help="min score to join the pool")
    ap.add_argument("--pool-size", type=int, default=20)
    ap.add_argument("--benchmarks", default="random,heuristic", help="fixed opponents for evaluation")
    ap.add_argument("--eval-every", type=int, default=50_000)
    ap.add_argument("--eval-games", type=int, default=40)
    ap.add_argument("--bc-games", type=int, default=0, help="warm start from heuristic over N games")
    ap.add_argument("--circular", action="store_true", help="wraparound CNN padding for torus boards")
    ap.add_argument("--net", default="256,256")
    ap.add_argument("--frame-stack", type=int, default=0, help="gym only: stack past observations")
    ap.add_argument("--normalize", action="store_true", help="gym only: VecNormalize")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", help="continue from this .zip")
    ap.add_argument("--set", action="append", default=[], help="override, e.g. --set gamma=0.999")
    args = ap.parse_args()

    is_gym = args.game.startswith("gym:") or args.game in GYM_GAMES
    if not is_gym and args.game not in GAMES:
        sys.exit(f"Unknown game {args.game!r}. Known: {sorted(GAMES)} {sorted(GYM_GAMES)}")
    if is_gym and args.algo == "mask_ppo":
        sys.exit("mask_ppo needs a Game with legal moves. Use ppo for a gym env.")
    run = Path("runs") / (args.name or f"{args.game.replace(':', '_')}_{args.algo}_{time.strftime('%m%d_%H%M%S')}")
    write_run_info(run, args.algo, vars(args))

    off_policy = args.algo in ("dqn", "qrdqn", "sac", "td3", "tqc")
    n_envs = args.n_envs or (1 if args.algo == "ars" else (1 if off_policy and is_gym else 8))
    vec_cls = SubprocVecEnv if args.subproc else DummyVecEnv

    make_game = None
    if is_gym:
        fns = [functools.partial(_gym_env, args.game, args.seed + i) for i in range(n_envs)]
    else:
        make_game = GAMES[args.game]
        spec = args.opponent + (",pool@2" if args.selfplay else "")
        fns = [functools.partial(_game_env, make_game, spec, str(run / "pool"), args.seed + i) for i in range(n_envs)]
    env = vec_cls(fns)
    if is_gym and args.frame_stack:
        env = VecFrameStack(env, args.frame_stack)
    if is_gym and args.normalize:
        env = VecNormalize(env, gamma=parse_overrides(args.set).get("gamma", 0.99))

    is_board = len(env.observation_space.shape) == 3
    net = [int(x) for x in args.net.split(",")]
    if args.resume:
        model, _ = load_model(args.resume, env=env, device="cuda" if is_board and torch.cuda.is_available() else "cpu")
        print(f"Resumed from {args.resume}")
    else:
        model = build_model(args.algo, env, parse_overrides(args.set), is_board, args.circular, net,
                            args.device, str(run / "tb"), args.seed)
    if args.bc_games and make_game:
        behaviour_clone(model, make_game, args.algo, args.bc_games)

    print(f"{args.algo} on {args.game}: {n_envs} envs, device {model.device}, saving to {run}")
    cb = Trainer(args, run, make_game)
    try:
        model.learn(args.steps, callback=cb, reset_num_timesteps=not args.resume, progress_bar=False)
    except KeyboardInterrupt:
        print("Interrupted, saving.")
    cb.model = model
    cb._evaluate()
    cb._save("last.zip")
    env.close()
    print(f"Best score {cb.best:.3f}. Next: python toolkit/rl/arena.py --game {args.game} --a {run}/best.zip --b heuristic")


if __name__ == "__main__":
    main()
