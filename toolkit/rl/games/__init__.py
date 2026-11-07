"""Add your game here. GAMES holds Game subclasses, GYM_GAMES holds gymnasium envs."""
from .connect4 import Connect4
from .duel import Duel

try:  # worked example, present only where the 2025 repo is on disk
    from .case_closed_example import ENGINE, CaseClosed
except ImportError:
    ENGINE = None

# from .mygame import MyGame
# from .mycontrol import MyControlEnv

GAMES = {
    "duel": Duel,
    "connect4": Connect4,
    # "mygame": MyGame,
}

if ENGINE is not None:
    GAMES["case_closed"] = CaseClosed

GYM_GAMES = {
    # "mycontrol": MyControlEnv,
}
