"""COPY THIS for single-player tasks: racing, control, driving a robot.

Register it in games/__init__.py, in GYM_GAMES. Then:
    python toolkit/rl/train.py --game mycontrol --algo sac --minutes 20

Continuous actions: try sac, tqc or td3 first, then ppo.
For a memoryless sensor (like 2023 Bots Race) add --frame-stack 4.
For rewards or observations on odd scales add --normalize.
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np


class MyControlEnv(gym.Env):
    def __init__(self):
        # TODO: match the challenge, e.g. 5 sensor inputs and 2 accelerations
        self.observation_space = gym.spaces.Box(-1.0, 1.0, shape=(5,), dtype=np.float32)
        self.action_space = gym.spaces.Box(-1.0, 1.0, shape=(2,), dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.t = 0
        # TODO: reset the simulator. Randomize the start or track, or the policy will
        # memorize one layout and fail on the judge's.
        return np.zeros(5, dtype=np.float32), {}

    def step(self, action):
        self.t += 1
        # TODO: advance the simulator, then reward progress, not just survival
        obs = np.zeros(5, dtype=np.float32)
        reward = 0.0
        terminated = False       # true end: finished or crashed
        truncated = self.t >= 1000  # time limit
        return obs, reward, terminated, truncated, {}
