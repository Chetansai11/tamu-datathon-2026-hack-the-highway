"""Turns any Game into a single-agent gymnasium env by putting an opponent inside it."""
from __future__ import annotations

import gymnasium as gym
import numpy as np

from agents import OpponentMix
from game_api import Game


class GameEnv(gym.Env):
    """The learner plays a random side each game against a sampled opponent.

    Illegal actions from models without masks become a legal move plus a small
    penalty, which teaches the rule without ending the game.
    """

    metadata = {"render_modes": []}

    def __init__(self, make_game, opponent: str = "random", pool_dir: str | None = None,
                 illegal_penalty: float = 0.05):
        self.make_game = make_game
        self.game: Game = make_game()
        self.mix = OpponentMix(opponent, pool_dir)
        self.illegal_penalty = illegal_penalty
        self.action_space = gym.spaces.Discrete(self.game.num_actions)
        self.observation_space = gym.spaces.Box(self.game.obs_low, self.game.obs_high,
                                                shape=self.game.obs_shape, dtype=np.float32)
        self.learner, self.seed_counter = 0, 0

    def _advance(self):
        """Play opponent moves until the learner must act (alternating games)."""
        g = self.game
        while not g.is_over() and self.learner not in g.to_move():
            g.step({p: self.opponent(g, p) for p in g.to_move()})

    def _obs(self):
        return self.game.observe(self.learner).astype(np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.seed_counter += 1
        self.game.reset(int(self.np_random.integers(2**31)))
        self.learner = int(self.np_random.integers(self.game.num_players))
        self.opponent = self.mix.sample()
        if hasattr(self.opponent, "new_game"):
            self.opponent.new_game()
        self._advance()
        return self._obs(), {}

    def action_masks(self) -> np.ndarray:
        if self.game.is_over():
            return np.ones(self.game.num_actions, dtype=bool)
        return self.game.legal_actions(self.learner).astype(bool)

    def step(self, action):
        g = self.game
        action = int(action)
        reward = 0.0
        mask = g.legal_actions(self.learner)
        if not mask[action]:
            action = int(np.flatnonzero(mask)[0])
            reward -= self.illegal_penalty
        joint = {self.learner: action}
        for p in g.to_move():
            if p != self.learner:
                joint[p] = self.opponent(g, p)
        g.step(joint)
        self._advance()
        reward += g.reward(self.learner)
        done = g.is_over()
        info = {}
        if done:
            result = g.result(self.learner)
            reward += result
            info["result"] = result
        return self._obs(), float(reward), done, False, info
