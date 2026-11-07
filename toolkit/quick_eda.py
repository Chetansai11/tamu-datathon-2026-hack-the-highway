"""First 15 minutes with any table: find what's broken before modelling.

    python toolkit/quick_eda.py data.csv
    python toolkit/quick_eda.py data.csv --target survived --out outputs/eda

Writes report.md plus charts. Checks for the flaws challenge authors like to plant:
sentinel values, inconsistent category spelling, numbers stored as text, duplicates,
impossible values, constant columns, and likely target leakage.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import charts

SENTINELS = {-1, -9, -99, -999, -9999, 99, 999, 9999, 99999}
NULL_STRINGS = {"", "na", "n/a", "nan", "none", "null", "unknown", "?", "-", "--", "missing"}


def load(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(p)
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    if p.suffix.lower() in {".json", ".jsonl"}:
        return pd.read_json(p, lines=p.suffix.lower() == ".jsonl")
    if p.suffix.lower() == ".tsv":
        return pd.read_csv(p, sep="\t", low_memory=False)
    return pd.read_csv(p, low_memory=False)


def as_text(s: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)


def looks_datetime(s: pd.Series) -> bool:
    sample = s.dropna().astype(str).head(200)
    if sample.empty or not sample.str.contains(r"\d").mean() > 0.9:
        return False
    if not sample.str.contains(r"[-/:]|\d{4}").mean() > 0.9:
        return False
    return pd.to_datetime(sample, errors="coerce", format="mixed").notna().mean() > 0.9


def column_flags(s: pd.Series) -> list[str]:
    flags: list[str] = []
    n = len(s)
    non_null = s.dropna()
    if non_null.empty:
        return ["entirely empty"]
    if non_null.nunique() == 1:
        flags.append(f"constant value {non_null.iloc[0]!r}")

    if as_text(s):
        text = non_null.astype(str)
        hidden_nulls = text.str.strip().str.lower().isin(NULL_STRINGS)
        if hidden_nulls.any():
            flags.append(f"{hidden_nulls.sum():,} disguised nulls {sorted(text[hidden_nulls].unique())[:5]}")
        numeric = pd.to_numeric(text.str.replace(r"[$,%\s]", "", regex=True), errors="coerce")
        rate = numeric.notna().mean()
        if rate > 0.8:
            bad = text[numeric.isna() & ~hidden_nulls]
            flags.append(f"numbers stored as text ({rate:.0%} parse); bad examples {list(bad.unique()[:5])}")
        elif text.nunique() <= 200:
            canon = text.str.strip().str.lower()
            if canon.nunique() < text.nunique():
                groups = text.groupby(canon).unique()
                ex = [list(v) for v in groups if len(v) > 1][:3]
                flags.append(f"inconsistent spelling/case: {ex}")
        if (text != text.str.strip()).any():
            flags.append("leading/trailing whitespace")
    elif pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        counts = non_null.value_counts()
        for v in SENTINELS:
            share = counts.get(v, 0) / len(non_null)
            is_outlier = v not in non_null.quantile([0.01, 0.99]).round(6).tolist() or abs(v) >= 999
            if share > 0.002 and is_outlier and (v < 0 or v > 3 * non_null.median()):
                flags.append(f"possible sentinel {v} ({counts[v]:,} rows)")
        q1, q3 = non_null.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr > 0:
            out = ((non_null < q1 - 3 * iqr) | (non_null > q3 + 3 * iqr)).sum()
            if out / n > 0.001:
                flags.append(f"{out:,} extreme outliers (3 IQR), range {non_null.min():g} to {non_null.max():g}")
        name = str(s.name).lower()
        if (non_null < 0).any() and re.search(r"age|price|qty|quantity|count|amount|cost|revenue|weight|height|duration|days", name):
            flags.append(f"{(non_null < 0).sum():,} negative values in a column that shouldn't be negative")
        if re.search(r"(^|_)age($|_)", name) and (non_null > 120).any():
            flags.append(f"{(non_null > 120).sum():,} impossible ages over 120")
    if s.isna().mean() > 0.4:
        flags.append(f"{s.isna().mean():.0%} missing")
    if non_null.nunique() == len(non_null) and len(non_null) > 20:
        flags.append("unique on every row (ID? drop before modelling)")
    return flags


def leak_scan(df: pd.DataFrame, target: str) -> list[str]:
    """Single-feature predictive power. Near-perfect means leakage or a post-outcome field."""
    from sklearn.metrics import roc_auc_score
    y = df[target]
    out = []
    if y.nunique() != 2:
        num = df.select_dtypes("number").drop(columns=[target], errors="ignore")
        if pd.api.types.is_numeric_dtype(y):
            c = num.corrwith(y).abs().sort_values(ascending=False)
            out = [f"{k}: |corr| {v:.3f}" for k, v in c.items() if v > 0.95]
        return out
    yb = (y == sorted(y.dropna().unique())[-1]).astype(int)
    for col in df.columns.drop(target):
        s = df[col]
        mask = s.notna() & y.notna()
        if mask.sum() < 30 or s[mask].nunique() < 2:
            continue
        if pd.api.types.is_numeric_dtype(s):
            x = s[mask]
        elif s.nunique() <= 100:
            x = s[mask].map(yb[mask].groupby(s[mask]).mean())
        else:
            continue
        auc = roc_auc_score(yb[mask], x)
        auc = max(auc, 1 - auc)
        if auc > 0.97:
            out.append(f"{col}: single-feature AUC {auc:.3f}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--target")
    ap.add_argument("--out", default="outputs/eda")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    charts.setup()

    df = load(args.path)
    r = [f"# EDA: {Path(args.path).name}", "",
         f"- Rows: {len(df):,}", f"- Columns: {df.shape[1]}",
         f"- Exact duplicate rows: {df.duplicated().sum():,}",
         f"- Memory: {df.memory_usage(deep=True).sum() / 1e6:.1f} MB", ""]

    dates = [c for c in df.columns if as_text(df[c]) and looks_datetime(df[c])]
    if dates:
        r += ["## Date columns", ""]
        for c in dates:
            d = pd.to_datetime(df[c], errors="coerce", format="mixed")
            r.append(f"- `{c}`: {d.min()} to {d.max()}, {df[c].notna().sum() - d.notna().sum():,} unparseable")
        r.append("")

    r += ["## Red flags", ""]
    n_flags = 0
    for c in df.columns:
        for f in column_flags(df[c]):
            if c in dates and "numbers stored as text" in f:
                continue
            r.append(f"- `{c}`: {f}")
            n_flags += 1
    if n_flags == 0:
        r.append("- none found by the automatic checks (still read the column descriptions)")

    if args.target:
        if args.target not in df.columns:
            sys.exit(f"--target {args.target!r} is not a column. Columns: {list(df.columns)}")
        leaks = leak_scan(df, args.target)
        r += ["", "## Possible target leakage", ""]
        r += [f"- `{x}`" for x in leaks] or ["- nothing suspiciously predictive on its own"]
        y = df[args.target]
        r += ["", f"## Target `{args.target}`", ""]
        if y.nunique() <= 20:
            r += [f"- {k}: {v:,} ({v / len(y):.1%})" for k, v in y.value_counts(dropna=False).items()]
        else:
            r.append(f"- mean {y.mean():.4g}, median {y.median():.4g}, std {y.std():.4g}, missing {y.isna().sum():,}")

    r += ["", "## Columns", "", "| column | type | missing | unique | example |", "|---|---|---|---|---|"]
    for c in df.columns:
        ex = df[c].dropna().iloc[0] if df[c].notna().any() else ""
        r.append(f"| {c} | {df[c].dtype} | {df[c].isna().mean():.1%} | {df[c].nunique():,} | {str(ex)[:40].replace('|', '/')} |")
    (out / "report.md").write_text("\n".join(r), encoding="utf-8")

    miss = df.isna().mean().mul(100)
    miss = miss[miss > 0]
    if len(miss):
        fig, _ = charts.ranked_bars(miss, title=f"{len(miss)} columns have missing values",
                                    subtitle="Share of rows missing (%)", fmt=lambda v: f"{v:.1f}%")
        charts.save(fig, "missing", out)
    num = df.select_dtypes("number")
    if num.shape[1] >= 2:
        fig, _ = charts.corr_heatmap(num)
        charts.save(fig, "correlations", out)

    print((out / "report.md").read_text(encoding="utf-8").split("## Columns")[0])
    print(f"Saved to {out.resolve()}")


if __name__ == "__main__":
    main()
