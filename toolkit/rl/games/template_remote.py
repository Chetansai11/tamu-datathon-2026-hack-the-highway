"""COPY THIS only if the game is reachable just by HTTP or as a separate program.

Have the Python source? Use template.py, because it's much faster and search works.

First capture a real exchange with their server and save the JSON to docs/, so you
map fields from facts rather than guesses. Then fill in the TODOs.
If their server handles one game at a time, train with --n-envs 1.
"""
from __future__ import annotations

import numpy as np

from remote import HttpTransport, ProcessTransport, RemoteGame  # noqa: F401


class MyRemoteGame(RemoteGame):
    num_players = 2
    num_actions = 4       # TODO
    obs_shape = (32,)     # TODO
    simultaneous = True   # TODO

    # TODO: choose one, and edit routes to match their API
    transport_factory = staticmethod(lambda: HttpTransport(
        "http://localhost:9000",
        routes=dict(reset=("POST", "/reset"), step=("POST", "/step"), state=("GET", "/state"))))
    # transport_factory = staticmethod(lambda: ProcessTransport(["./their_game", "--json"]))

    def encode(self, actions):
        # TODO: convert {player: action} into the JSON they expect
        return {"moves": [actions.get(0), actions.get(1)]}

    def read_state(self, raw):
        # TODO: convert their JSON into this shape
        return dict(
            obs={0: np.array(raw["p0"], dtype=np.float32), 1: np.array(raw["p1"], dtype=np.float32)},
            legal=None,               # or {0: [...], 1: [...]}
            to_move=[0, 1],
            over=raw["done"],
            result={0: raw.get("r0", 0), 1: raw.get("r1", 0)},
        )
