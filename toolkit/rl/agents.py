"""Every kind of player behind one spec string, used by training, the arena and serving.

    random                 uniform legal move
    heuristic              Game.heuristic()
    mcts:200               search for 200 ms
    mcts:200:0.5           search with half of rollout moves from the heuristic
    runs/x/best.zip        trained stable-baselines3 model
    runs/x/policy.pt       exported TorchScript policy (CPU, no SB3 needed)
"""
from __future__ import annotations

import random as _random
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

import search


def random_agent(game, player):
    return int(np.random.choice(np.flatnonzero(game.legal_actions(player))))


def heuristic_agent(game, player):
    return game.heuristic(player)


class PolicyAgent:
    """Trained model. Stochastic by default as an opponent, greedy when competing."""

    def __init__(self, path: str | None = None, deterministic: bool = True, model=None, algo=None):
        from models import load_model
        self.model, self.algo = (model, algo) if model is not None else load_model(path)
        self.deterministic = deterministic
        self.state, self.start = None, np.ones(1, dtype=bool)

    def new_game(self):
        self.state, self.start = None, np.ones(1, dtype=bool)

    def __call__(self, game, player):
        obs = game.observe(player)
        mask = game.legal_actions(player)
        if self.algo == "mask_ppo":
            action, _ = self.model.predict(obs, deterministic=self.deterministic, action_masks=mask)
        elif self.algo == "recurrent_ppo":
            action, self.state = self.model.predict(obs, state=self.state, episode_start=self.start,
                                                    deterministic=self.deterministic)
            self.start = np.zeros(1, dtype=bool)
        else:
            action, _ = self.model.predict(obs, deterministic=self.deterministic)
        action = int(action)
        if not mask[action]:  # models without masks can pick illegal moves
            action = int(np.flatnonzero(mask)[0])
        return action


class TorchScriptAgent:
    """Exported policy: fast, CPU only, and needs just torch in the Docker image."""

    def __init__(self, path: str):
        torch.set_num_threads(1)  # steadier move times inside a container
        self.net = torch.jit.load(path, map_location="cpu").eval()

    @torch.inference_mode()
    def __call__(self, game, player):
        obs = torch.as_tensor(game.observe(player)).float().unsqueeze(0)
        logits = self.net(obs).squeeze(0).numpy()
        mask = game.legal_actions(player)
        logits[~mask] = -np.inf
        return int(np.argmax(logits))


def load_agent(spec: str, deterministic: bool = True):
    if spec == "random":
        return random_agent
    if spec == "heuristic":
        return heuristic_agent
    if spec.startswith("mcts"):
        parts = spec.split(":")
        ms = float(parts[1]) if len(parts) > 1 else 200
        smart = float(parts[2]) if len(parts) > 2 else 0.0
        return lambda game, player: search.mcts(game, player, time_ms=ms, smart=smart)
    if spec.endswith(".pt"):
        return TorchScriptAgent(spec)
    if spec.endswith(".zip"):
        return PolicyAgent(spec, deterministic)
    raise ValueError(f"Unknown agent spec: {spec}")


@lru_cache(maxsize=12)
def _cached_policy(path: str):
    return PolicyAgent(path, deterministic=False)


class OpponentMix:
    """Opponent sampled per game. 'random@0.2,heuristic@0.4,pool@0.4'.

    `pool` reads snapshots from disk, so it also works inside subprocess envs.
    """

    def __init__(self, spec: str, pool_dir: str | None = None):
        self.items = []
        for part in spec.split(","):
            name, _, weight = part.partition("@")
            self.items.append((name.strip(), float(weight or 1)))
        self.pool_dir = Path(pool_dir) if pool_dir else None

    def sample(self):
        names = [n for n, _ in self.items]
        weights = [w for _, w in self.items]
        name = _random.choices(names, weights)[0]
        if name == "pool":
            snaps = sorted(self.pool_dir.glob("snap_*.zip")) if self.pool_dir else []
            if not snaps:
                return heuristic_agent
            # Favour recent snapshots but keep old ones, so the policy can't forget them.
            recent = snaps[-5:]
            pick = _random.choice(recent) if _random.random() < 0.7 else _random.choice(snaps)
            return _cached_policy(str(pick))
        return load_agent(name, deterministic=False)
