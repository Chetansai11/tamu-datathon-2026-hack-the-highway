"""Demo: simultaneous two-player trail game on a wraparound grid. Used to test the kit."""
from __future__ import annotations

from collections import deque

import numpy as np

from game_api import Game

MOVES = [(-1, 0), (1, 0), (0, -1), (0, 1)]
OPPOSITE = [1, 0, 3, 2]


class Duel(Game):
    num_actions = 4
    simultaneous = True

    def __init__(self, size: int = 10, max_turns: int = 120):
        self.size = size
        self.max_turns = max_turns
        self.obs_shape = (4, size, size)

    def reset(self, seed=None):
        rng = np.random.default_rng(seed)
        n = self.size
        self.grid = np.zeros((n, n), dtype=np.int8)  # 0 empty, 1 and 2 trails
        r = int(rng.integers(n))
        self.heads = [(r, n // 4), ((r + n // 2) % n, 3 * n // 4)]
        self.last = [3, 2]
        self.grid[self.heads[0]] = 1
        self.grid[self.heads[1]] = 2
        self.alive = [True, True]
        self.turn = 0
        self.survived = False

    def to_move(self):
        return [0, 1]

    def _next(self, player, action):
        r, c = self.heads[player]
        dr, dc = MOVES[action]
        return (r + dr) % self.size, (c + dc) % self.size

    def legal_actions(self, player):
        mask = np.array([self.grid[self._next(player, a)] == 0 and a != OPPOSITE[self.last[player]]
                         for a in range(4)])
        if mask.any():
            return mask
        return np.array([a != OPPOSITE[self.last[player]] for a in range(4)])

    def observe(self, player):
        opp = 1 - player
        obs = np.zeros(self.obs_shape, dtype=np.float32)
        obs[0] = self.grid == player + 1
        obs[1] = self.grid == opp + 1
        obs[2][self.heads[player]] = 1
        obs[3][self.heads[opp]] = 1
        return obs

    def step(self, actions):
        targets = [self._next(p, actions[p]) for p in (0, 1)]
        self.alive = [self.grid[t] == 0 for t in targets]
        if targets[0] == targets[1]:
            self.alive = [False, False]
        for p in (0, 1):
            self.last[p] = actions[p]
            if self.alive[p]:
                self.heads[p] = targets[p]
                self.grid[targets[p]] = p + 1
        self.turn += 1

    def is_over(self):
        return not all(self.alive) or self.turn >= self.max_turns

    def result(self, player):
        if self.alive[player] == self.alive[1 - player]:
            return 0.0
        return 1.0 if self.alive[player] else -1.0

    def reward(self, player):
        return 0.002

    def _open_area(self, start):
        seen = {start}
        queue = deque([start])
        while queue:
            r, c = queue.popleft()
            for dr, dc in MOVES:
                nxt = ((r + dr) % self.size, (c + dc) % self.size)
                if nxt not in seen and self.grid[nxt] == 0:
                    seen.add(nxt)
                    queue.append(nxt)
        return len(seen)

    def heuristic(self, player):
        """Move toward the largest open region."""
        legal = np.flatnonzero(self.legal_actions(player))
        scored = []
        for a in legal:
            target = self._next(player, a)
            scored.append((self._open_area(target) if self.grid[target] == 0 else -1, a))
        return int(max(scored)[1])

    def clone(self):
        c = object.__new__(Duel)
        c.__dict__.update(self.__dict__)
        c.grid = self.grid.copy()
        c.heads = list(self.heads)
        c.last = list(self.last)
        c.alive = list(self.alive)
        return c
