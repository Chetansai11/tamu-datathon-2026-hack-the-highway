"""Model blocks. One registry of algorithms, presets and networks.

Add a model by adding one line to ALGOS. Override anything from the command line:
    --set learning_rate=1e-4 --set gamma=0.999
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import torch
import torch.nn as nn
from sb3_contrib import ARS, QRDQN, TQC, TRPO, MaskablePPO, RecurrentPPO
from stable_baselines3 import A2C, DQN, PPO, SAC, TD3
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

ON_POLICY = dict(learning_rate=3e-4, n_steps=1024, batch_size=512, n_epochs=4, gamma=0.995,
                 gae_lambda=0.95, clip_range=0.2, ent_coef=0.01, vf_coef=0.5)
OFF_POLICY_D = dict(learning_rate=1e-4, buffer_size=200_000, learning_starts=5_000, batch_size=256,
                    gamma=0.995, train_freq=4, target_update_interval=2_000,
                    exploration_fraction=0.3, exploration_final_eps=0.05)
OFF_POLICY_C = dict(learning_rate=3e-4, buffer_size=300_000, learning_starts=5_000, batch_size=256,
                    gamma=0.99, tau=0.005)

# name: (class, policy, presets, supports discrete, supports continuous)
ALGOS = {
    "mask_ppo":      (MaskablePPO,  "MlpPolicy",     ON_POLICY, True, False),
    "ppo":           (PPO,          "MlpPolicy",     ON_POLICY, True, True),
    "recurrent_ppo": (RecurrentPPO, "MlpLstmPolicy", ON_POLICY, True, True),
    "a2c":           (A2C,          "MlpPolicy",     dict(learning_rate=7e-4, n_steps=32, gamma=0.995, ent_coef=0.01), True, True),
    "trpo":          (TRPO,         "MlpPolicy",     dict(n_steps=1024, batch_size=256, gamma=0.995), True, True),
    "ars":           (ARS,          "MlpPolicy",     dict(), True, True),
    "dqn":           (DQN,          "MlpPolicy",     OFF_POLICY_D, True, False),
    "qrdqn":         (QRDQN,        "MlpPolicy",     OFF_POLICY_D, True, False),
    "sac":           (SAC,          "MlpPolicy",     OFF_POLICY_C, False, True),
    "td3":           (TD3,          "MlpPolicy",     OFF_POLICY_C, False, True),
    "tqc":           (TQC,          "MlpPolicy",     OFF_POLICY_C, False, True),
}


class SmallCNN(BaseFeaturesExtractor):
    """Keeps board resolution, unlike the Atari CNN, which assumes large images.

    circular=True wraps padding for boards with torus (wraparound) edges.
    """

    def __init__(self, observation_space, features_dim: int = 256, channels: int = 64,
                 blocks: int = 3, circular: bool = False):
        super().__init__(observation_space, features_dim)
        c, h, w = observation_space.shape
        mode = "circular" if circular else "zeros"
        layers: list[nn.Module] = []
        in_c = c
        for _ in range(blocks):
            layers += [nn.Conv2d(in_c, channels, 3, padding=1, padding_mode=mode), nn.ReLU()]
            in_c = channels
        self.conv = nn.Sequential(*layers, nn.Conv2d(channels, 16, 1), nn.ReLU(), nn.Flatten())
        with torch.no_grad():
            n = self.conv(torch.zeros(1, c, h, w)).shape[1]
        self.head = nn.Sequential(nn.Linear(n, features_dim), nn.ReLU())

    def forward(self, x):
        return self.head(self.conv(x))


def parse_overrides(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        try:
            out[key] = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            out[key] = value
    return out


def build_model(algo: str, env, overrides: dict, is_board: bool, circular: bool, net: list[int],
                device: str, log_dir: str | None, seed: int):
    if algo not in ALGOS:
        raise SystemExit(f"Unknown algo {algo!r}. Choose from {sorted(ALGOS)}")
    cls, policy, preset, discrete, continuous = ALGOS[algo]
    is_discrete = hasattr(env.action_space, "n")
    if (is_discrete and not discrete) or (not is_discrete and not continuous):
        kind = "discrete" if is_discrete else "continuous"
        ok = [k for k, v in ALGOS.items() if v[3 if is_discrete else 4]]
        raise SystemExit(f"{algo} can't handle {kind} actions. Use one of {ok}")

    kwargs = dict(preset)
    if not is_discrete:
        for k in ("exploration_fraction", "exploration_final_eps", "target_update_interval"):
            kwargs.pop(k, None)
    policy_kwargs: dict = {}
    if algo != "ars":
        policy_kwargs["net_arch"] = net
    if is_board:
        policy_kwargs.update(features_extractor_class=SmallCNN,
                             features_extractor_kwargs=dict(circular=circular))
        if algo in ("sac", "td3", "tqc"):
            policy_kwargs["share_features_extractor"] = False
        if algo == "ars":
            raise SystemExit("ars needs flat observations, not boards.")
    kwargs.update(overrides)
    if device == "auto":  # MLPs run faster on CPU, CNNs on GPU
        device = "cuda" if is_board and torch.cuda.is_available() else "cpu"
    if algo == "ars":
        return cls(policy, env, device=device, seed=seed, verbose=0, **kwargs)
    return cls(policy, env, policy_kwargs=policy_kwargs, device=device, seed=seed, verbose=0,
               tensorboard_log=log_dir, **kwargs)


def load_model(path: str, env=None, device: str = "cpu"):
    """Load a saved model. algo.txt beside it records which class to use."""
    p = Path(path)
    algo_file = p.parent / "algo.txt"
    if not algo_file.exists():
        raise FileNotFoundError(f"{algo_file} is missing, so the model class is unknown.")
    algo = algo_file.read_text().strip()
    return ALGOS[algo][0].load(str(p), env=env, device=device), algo


def write_run_info(run: Path, algo: str, args: dict) -> None:
    (run / "pool").mkdir(parents=True, exist_ok=True)
    (run / "algo.txt").write_text(algo)
    (run / "pool" / "algo.txt").write_text(algo)
    (run / "config.json").write_text(json.dumps(args, indent=2, default=str))
