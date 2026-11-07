"""COPY THIS FILE when the game is announced.

    copy toolkit/rl/games/template.py to toolkit/rl/games/mygame.py
    fill in every TODO
    add it to GAMES in toolkit/rl/games/__init__.py
    python toolkit/rl/check_game.py mygame        <- do this before any training

Rule: import the organizers' game file here. Never re-implement their rules: your
copy will drift from the judge. Their source file is the real rulebook.
"""
from __future__ import annotations

import numpy as np

from game_api import Game

# TODO: from organizers_game_file import TheirGame


class MyGame(Game):
    num_players = 2
    num_actions = 4           # TODO
    obs_shape = (4, 18, 20)   # TODO: (C, H, W) for boards, (N,) for flat vectors
    simultaneous = True       # TODO: True if both players move at once

    def reset(self, seed=None):
        self.rng = np.random.default_rng(seed)
        self.g = None  # TODO: TheirGame()

    def to_move(self):
        return [0, 1] if self.simultaneous else [self.g.current_player]  # TODO

    def legal_actions(self, player):
        # TODO: mark moves that are illegal or instantly fatal as False, but if every
        # move is fatal return all True. A mask of all False crashes training.
        return np.ones(self.num_actions, dtype=bool)

    def observe(self, player):
        # TODO: always from `player`'s view: channel 0 = me, channel 1 = opponent.
        # Scalars such as boosts left go in as a constant channel, value / max_value.
        return np.zeros(self.obs_shape, dtype=np.float32)

    def step(self, actions):
        raise NotImplementedError  # TODO: self.g.apply(actions[0], actions[1])

    def is_over(self):
        raise NotImplementedError  # TODO

    def result(self, player):
        raise NotImplementedError  # TODO: +1 win, 0 draw, -1 loss

    # Optional but high value, do after the five above:
    # def heuristic(self, player): best hand-written move
    # def reward(self, player):    small shaping reward
    # def evaluate(self, player):  board score in [-1, 1] for search
    # def clone(self):             fast copy for search
