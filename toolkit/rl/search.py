"""Time-limited Monte Carlo Tree Search that needs only Game.clone().

Works for alternating games and simultaneous games (decoupled UCT: each player
picks its move independently at a node). No training needed, so this is often your
strongest agent in the first hours. Plug in Game.evaluate() or a trained value to
stop rollouts early, and Game.heuristic() to make rollouts smarter.
"""
from __future__ import annotations

import math
import time

import numpy as np


class Node:
    __slots__ = ("stats", "children", "players")

    def __init__(self, game):
        self.players = game.to_move()
        # per player: action -> [visits, total value]
        self.stats = {p: {int(a): [0, 0.0] for a in np.flatnonzero(game.legal_actions(p))}
                      for p in self.players}
        self.children = {}

    def select(self, c: float) -> dict[int, int]:
        joint = {}
        for p in self.players:
            actions = self.stats[p]
            total = sum(v[0] for v in actions.values()) + 1
            best, best_score = None, -math.inf
            for a, (n, w) in actions.items():
                score = math.inf if n == 0 else w / n + c * math.sqrt(math.log(total) / n)
                if score > best_score:
                    best, best_score = a, score
            joint[p] = best
        return joint


def rollout(game, root_players, smart: float, depth: int) -> dict[int, float]:
    for _ in range(depth):
        if game.is_over():
            return {p: game.result(p) for p in root_players}
        joint = {}
        for p in game.to_move():
            if smart and np.random.random() < smart:
                joint[p] = game.heuristic(p)
            else:
                joint[p] = int(np.random.choice(np.flatnonzero(game.legal_actions(p))))
        game.step(joint)
    if game.is_over():
        return {p: game.result(p) for p in root_players}
    return {p: game.evaluate(p) for p in root_players}


def mcts(game, player: int, time_ms: float = 200, c: float = 1.2, smart: float = 0.0,
         depth: int = 60) -> int:
    """Best action for `player` within time_ms. smart = share of heuristic rollout moves."""
    deadline = time.perf_counter() + time_ms / 1000
    root = Node(game)
    players = list(range(game.num_players))
    iters = 0
    while time.perf_counter() < deadline or iters == 0:
        iters += 1
        g = game.clone()
        node, path = root, []
        while True:
            joint = node.select(c)
            path.append((node, joint))
            g.step(joint)
            if g.is_over():
                values = {p: g.result(p) for p in players}
                break
            key = tuple(sorted(joint.items()))
            child = node.children.get(key)
            if child is None:
                node.children[key] = Node(g)
                values = rollout(g, players, smart, depth)
                break
            node = child
        for n, joint in path:
            for p, a in joint.items():
                n.stats[p][a][0] += 1
                n.stats[p][a][1] += values[p]
    if player not in root.stats:
        return int(np.flatnonzero(game.legal_actions(player))[0])
    return max(root.stats[player].items(), key=lambda kv: kv[1][0])[0]
