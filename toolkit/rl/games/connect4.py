"""Demo: alternating-turn board game. Used to test masks, search and side swapping."""
from __future__ import annotations

import numpy as np

from game_api import Game

ROWS, COLS = 6, 7


class Connect4(Game):
    num_actions = COLS
    obs_shape = (3, ROWS, COLS)

    def reset(self, seed=None):
        self.b = np.zeros((ROWS, COLS), dtype=np.int8)
        self.player = 0
        self.winner = None
        self.moves = 0

    def to_move(self):
        return [self.player]

    def legal_actions(self, player):
        return self.b[0] == 0

    def observe(self, player):
        return np.stack([self.b == player + 1, self.b == (1 - player) + 1,
                         np.full((ROWS, COLS), self.player == player)]).astype(np.float32)

    def _wins(self, r, c, mark):
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            run = 1
            for s in (1, -1):
                i, j = r + s * dr, c + s * dc
                while 0 <= i < ROWS and 0 <= j < COLS and self.b[i, j] == mark:
                    run += 1
                    i += s * dr
                    j += s * dc
            if run >= 4:
                return True
        return False

    def step(self, actions):
        col = actions[self.player]
        row = int(np.flatnonzero(self.b[:, col] == 0)[-1])
        mark = self.player + 1
        self.b[row, col] = mark
        self.moves += 1
        if self._wins(row, col, mark):
            self.winner = self.player
        self.player = 1 - self.player

    def is_over(self):
        return self.winner is not None or self.moves == ROWS * COLS

    def result(self, player):
        if self.winner is None:
            return 0.0
        return 1.0 if self.winner == player else -1.0

    def heuristic(self, player):
        """Win now, else block, else prefer the centre."""
        legal = np.flatnonzero(self.legal_actions(player))
        for mark_player in (player, 1 - player):
            for col in legal:
                row = int(np.flatnonzero(self.b[:, col] == 0)[-1])
                self.b[row, col] = mark_player + 1
                hit = self._wins(row, col, mark_player + 1)
                self.b[row, col] = 0
                if hit:
                    return int(col)
        return int(legal[np.argmin(np.abs(legal - COLS // 2))])

    def clone(self):
        c = object.__new__(Connect4)
        c.__dict__.update(self.__dict__)
        c.b = self.b.copy()
        return c
