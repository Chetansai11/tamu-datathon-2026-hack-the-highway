"""Export a trained model to TorchScript, so the submission needs only CPU torch.

    python toolkit/rl/export.py runs/x/best.zip --out runs/x/policy.pt

Drops stable-baselines3 from the Docker image and checks the export matches the original.
Recurrent models keep hidden state, so run those with SB3 instead.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).parent))
from models import load_model


class ActorLogits(nn.Module):
    def __init__(self, policy):
        super().__init__()
        self.policy = policy

    def forward(self, obs):
        features = self.policy.extract_features(obs)
        return self.policy.action_net(self.policy.mlp_extractor.forward_actor(features))


class QValues(nn.Module):
    def __init__(self, policy):
        super().__init__()
        self.q = policy.q_net

    def forward(self, obs):
        return self.q(obs)


class QuantileMean(nn.Module):
    def __init__(self, policy):
        super().__init__()
        self.q = policy.quantile_net

    def forward(self, obs):
        return self.q(obs).mean(dim=1)


class ContinuousActor(nn.Module):
    def __init__(self, policy):
        super().__init__()
        self.actor = policy.actor

    def forward(self, obs):
        return self.actor(obs, deterministic=True) if hasattr(self.actor, "action_dist") else self.actor(obs)


def wrap(model, algo: str) -> nn.Module:
    if algo in ("mask_ppo", "ppo", "a2c", "trpo"):
        return ActorLogits(model.policy)
    if algo == "dqn":
        return QValues(model.policy)
    if algo == "qrdqn":
        return QuantileMean(model.policy)
    if algo in ("sac", "td3", "tqc"):
        return ContinuousActor(model.policy)
    raise SystemExit(f"Export isn't supported for {algo}. Serve the .zip with PolicyAgent instead.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--out")
    args = ap.parse_args()
    model, algo = load_model(args.model)
    out = Path(args.out or Path(args.model).with_name("policy.pt"))
    net = wrap(model, algo).eval()
    example = torch.as_tensor(model.observation_space.sample().astype(np.float32)).unsqueeze(0)
    with torch.no_grad():
        traced = torch.jit.trace(net, example, check_trace=False)
    traced.save(str(out))

    loaded = torch.jit.load(str(out), map_location="cpu").eval()
    with torch.no_grad():
        batch = torch.as_tensor(np.stack([model.observation_space.sample() for _ in range(16)]).astype(np.float32))
        same = torch.allclose(net(batch), loaded(batch), atol=1e-5)
    if not same:
        sys.exit("Export doesn't match the original model.")
    size = out.stat().st_size / 1e6
    print(f"Exported {algo} to {out} ({size:.1f} MB). Output matches the original on 16 samples.")


if __name__ == "__main__":
    main()
