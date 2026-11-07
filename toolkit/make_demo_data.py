"""Synthetic practice data with planted flaws. Run: python toolkit/make_demo_data.py"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
out = Path("data/demo")
out.mkdir(parents=True, exist_ok=True)

# Messy tabular classification, shaped like a "find the flaws, explain survival" challenge.
n = 4000
age = rng.normal(62, 16, n).clip(18, 97).round()
severity = rng.integers(1, 5, n)
bp = rng.normal(125, 18, n).round()
lab = rng.lognormal(1.0, 0.5, n).round(2)
smoker = rng.random(n) < 0.3
logit = -5.0 + 0.035 * age + 0.75 * severity + 0.5 * smoker + 0.25 * lab - 0.012 * (bp - 120)
died = rng.random(n) < 1 / (1 + np.exp(-logit))
df = pd.DataFrame({
    "patient_id": [f"P{i:05d}" for i in range(n)],
    "age": age, "severity": severity, "bp_sys": bp, "lab_value": lab,
    "sex": rng.choice(["Male", "male", "M ", "Female", "female", "F"], n),
    "smoker": np.where(smoker, "yes", "no"),
    "cost": (rng.lognormal(8, 0.6, n)).round(2).astype(str),
    "discharge_code": np.where(died, 20, rng.choice([1, 2, 3], n)),  # leakage
    "survived": (~died).astype(int),
})
df.loc[rng.choice(n, 180, replace=False), "bp_sys"] = -999  # sentinel
df.loc[rng.choice(n, 40, replace=False), "age"] = 999       # impossible
df.loc[rng.choice(n, 300, replace=False), "lab_value"] = np.nan
df.loc[rng.choice(n, 60, replace=False), "smoker"] = "unknown"
df = pd.concat([df, df.sample(25, random_state=1)])         # duplicates
df.to_csv(out / "patients.csv", index=False)

# Transactions, shaped like a restaurant inventory / dashboard challenge.
days = pd.date_range("2026-01-01", "2026-09-30")
items = {"Beef bowl": ("Mains", 13.5), "Chicken noodles": ("Mains", 12.0), "Dumplings": ("Sides", 7.5),
         "Spring rolls": ("Sides", 6.0), "Milk tea": ("Drinks", 5.0), "Jasmine tea": ("Drinks", 3.5)}
rows = []
for d in days:
    weekend = 1.4 if d.day_of_week >= 5 else 1.0
    for store in ("Northgate", "Century Sq"):
        for item, (cat, price) in items.items():
            base = 30 if cat == "Mains" else 18
            q = rng.poisson(base * weekend * (1.15 if store == "Northgate" else 0.9) * (1 + 0.0015 * d.day_of_year))
            rows.append((d.date().isoformat(), store, cat, item, q, round(q * price, 2)))
pd.DataFrame(rows, columns=["date", "store", "category", "item", "qty", "revenue"]).to_csv(out / "orders.csv", index=False)
print("Wrote", *sorted(p.name for p in out.iterdir()))
