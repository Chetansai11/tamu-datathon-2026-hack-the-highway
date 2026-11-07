"""Bridge to an environment you can only reach from outside: a server or separate program.

If the organizers give you Python source, DON'T use this. Import it directly as in
games/template.py: it's far faster, and search needs clone(). Use this when the game
only exists as an HTTP service or a compiled or non-Python program.

    class MyRemote(RemoteGame):
        num_actions, obs_shape, simultaneous = 4, (8,), True
        transport_factory = staticmethod(lambda: HttpTransport("http://localhost:9000"))
        def encode(self, actions): ...
        def read_state(self, raw): ...

Copy games/template_remote.py to start.
"""
from __future__ import annotations

import json
import subprocess
import threading

import numpy as np
import requests

from game_api import Game


class HttpTransport:
    """routes maps reset, step and state to (method, path)."""

    DEFAULT_ROUTES = dict(reset=("POST", "/reset"), step=("POST", "/step"), state=("GET", "/state"))

    def __init__(self, base_url: str, routes: dict | None = None, headers: dict | None = None, timeout: float = 10):
        self.base = base_url.rstrip("/")
        self.routes = {**self.DEFAULT_ROUTES, **(routes or {})}
        self.session = requests.Session()  # reuses the connection, much faster per step
        self.session.headers.update(headers or {})
        self.timeout = timeout

    def call(self, name: str, payload: dict | None = None) -> dict:
        method, path = self.routes[name]
        kwargs = {"params": payload} if method == "GET" else {"json": payload or {}}
        r = self.session.request(method, self.base + path, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self.session.close()


class ProcessTransport:
    """Talks JSON lines over stdin and stdout to a program you start.

    Sends {"cmd": "step", ...} and expects one JSON line back. Change `line_format` for
    other protocols.
    """

    def __init__(self, command: list[str], timeout: float = 10, cwd: str | None = None):
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd=cwd)
        self.timeout = timeout

    def line_format(self, name: str, payload: dict | None) -> str:
        return json.dumps({"cmd": name, **(payload or {})})

    def call(self, name: str, payload: dict | None = None) -> dict:
        if self.proc.poll() is not None:
            raise RuntimeError(f"Game process exited with code {self.proc.returncode}")
        self.proc.stdin.write(self.line_format(name, payload) + "\n")
        self.proc.stdin.flush()
        box: list[str] = []
        reader = threading.Thread(target=lambda: box.append(self.proc.stdout.readline()), daemon=True)
        reader.start()
        reader.join(self.timeout)
        if not box or not box[0]:
            self.close()
            raise TimeoutError(f"No reply to {name!r} within {self.timeout}s")
        return json.loads(box[0])

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()


class RemoteGame(Game):
    """A Game whose rules live elsewhere. Override encode and read_state.

    read_state returns a dict with:
        obs:     {player: array}
        legal:   {player: bool array}, or leave it out if every action is always legal
        to_move: list of players
        over:    bool
        result:  {player: +1/0/-1}, when over
    """

    supports_clone = False
    transport_factory = None

    def __init__(self):
        self.transport = type(self).transport_factory()
        self.view: dict = {}

    def encode(self, actions: dict[int, int]) -> dict:
        raise NotImplementedError

    def read_state(self, raw: dict) -> dict:
        raise NotImplementedError

    def reset_payload(self, seed) -> dict:
        return {} if seed is None else {"seed": int(seed)}

    def reset(self, seed=None):
        self.view = self.read_state(self.transport.call("reset", self.reset_payload(seed)))

    def to_move(self):
        return self.view["to_move"]

    def legal_actions(self, player):
        legal = self.view.get("legal")
        return np.ones(self.num_actions, dtype=bool) if legal is None else np.asarray(legal[player], dtype=bool)

    def observe(self, player):
        return np.asarray(self.view["obs"][player], dtype=np.float32)

    def step(self, actions):
        self.view = self.read_state(self.transport.call("step", self.encode(actions)))

    def is_over(self):
        return bool(self.view["over"])

    def result(self, player):
        return float(self.view["result"][player])

    def clone(self):
        raise NotImplementedError("A remote game can't be cloned, so MCTS is unavailable unless it offers a save-state API.")

    def __getstate__(self):
        raise TypeError("Remote games open connections in __init__, so build one per process instead of pickling.")
