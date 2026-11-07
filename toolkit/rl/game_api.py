"""The one contract between a game and everything else in this kit.

Tomorrow you write one Game subclass (start from games/template.py) that wraps the
organizers' game logic. train.py, search.py, arena.py and serve.py then all work on it.

For a single-player continuous task (like the 2023 Bots Race), skip this file and
use a gymnasium env instead: see games/template_single.py.
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod

import numpy as np


class Game(ABC):
    num_players: int = 2
    num_actions: int
    obs_shape: tuple[int, ...]  # (C, H, W) uses the CNN; (N,) uses an MLP
    simultaneous: bool = False  # True when all players move at once (grid racers)
    obs_low: float = 0.0
    obs_high: float = 1.0

    @abstractmethod
    def reset(self, seed: int | None = None) -> None:
        """Start a new game."""

    @abstractmethod
    def to_move(self) -> list[int]:
        """Players acting now. Everyone if simultaneous, otherwise one player."""

    @abstractmethod
    def legal_actions(self, player: int) -> np.ndarray:
        """Boolean mask of length num_actions. Never all False while the game is live."""

    @abstractmethod
    def observe(self, player: int) -> np.ndarray:
        """Observation from this player's point of view, so one policy can play either side."""

    @abstractmethod
    def step(self, actions: dict[int, int]) -> None:
        """Apply {player: action} for every player in to_move()."""

    @abstractmethod
    def is_over(self) -> bool: ...

    @abstractmethod
    def result(self, player: int) -> float:
        """Final outcome once is_over(): +1 win, 0 draw, -1 loss."""

    def reward(self, player: int) -> float:
        """Optional shaped reward for the last step. Keep it small next to +/-1.

        Shaping is the main knob. Start at 0, add only what fixes observed bad play.
        """
        return 0.0

    def heuristic(self, player: int) -> int:
        """Optional hand-written policy. Used as a benchmark, opponent and BC teacher."""
        legal = np.flatnonzero(self.legal_actions(player))
        return int(np.random.choice(legal))

    def evaluate(self, player: int) -> float:
        """Optional value in [-1, 1] for cutting search short, instead of random rollouts."""
        return 0.0

    def clone(self) -> "Game":
        """Copy for search. Override with something faster: search speed depends on it."""
        return copy.deepcopy(self)
