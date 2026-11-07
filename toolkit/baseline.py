"""Honest baseline in one command: scoreboard, feature drivers, predictions.

    python toolkit/baseline.py train.csv --target survived
    python toolkit/baseline.py train.csv --target y --id row_id --test test.csv --metric f1
    python toolkit/baseline.py sales.csv --target units --time date
    python toolkit/baseline.py visits.csv --target y --group patient_id

Validation is chosen from your flags:
    --time   forward-chaining folds (never trains on the future)
    --group  GroupKFold (the same entity never appears in train and validation)
    default  stratified K-fold (classification) or K-fold (regression)

Compares a dummy, a linear model and LightGBM. If LightGBM barely beats the dummy,
fix the data, not the model. Outputs go to outputs/baseline/.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (average_precision_score, f1_score, log_loss, mean_absolute_error,
                             precision_recall_curve, r2_score, roc_auc_score, root_mean_squared_error)
from sklearn.model_selection import GroupKFold, KFold, StratifiedKFold, TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
import charts
from quick_eda import load

warnings.filterwarnings("ignore", category=UserWarning)
SEED = 42
HIGHER_IS_BETTER = {"auc", "ap", "f1", "macro_f1", "r2"}


def time_features(df: pd.DataFrame, col: str) -> pd.DataFrame:
    d = pd.to_datetime(df[col], errors="coerce", format="mixed")
    out = df.drop(columns=[col]).copy()
    out[f"{col}_dow"] = d.dt.dayofweek
    out[f"{col}_month"] = d.dt.month
    out[f"{col}_hour"] = d.dt.hour
    return out.loc[:, out.nunique(dropna=False) > 1]


def prepare(df: pd.DataFrame, drop: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Numeric + low-cardinality category columns. Reports what it dropped."""
    X = df.drop(columns=[c for c in drop if c in df.columns]).copy()
    removed = []
    for c in list(X.columns):
        s = X[c]
        if pd.api.types.is_bool_dtype(s):
            X[c] = s.astype(int)
        elif pd.api.types.is_numeric_dtype(s):
            continue
        else:
            parsed = pd.to_numeric(s, errors="coerce")
            if parsed.notna().mean() > 0.9 * max(s.notna().mean(), 1e-9):
                X[c] = parsed
            elif s.nunique() > min(200, 0.5 * len(s)):
                removed.append(c)
                X = X.drop(columns=c)
            else:
                X[c] = s.astype("string").str.strip().str.lower().astype("category")
    return X, removed


def linear_model(X: pd.DataFrame, task: str):
    num = X.select_dtypes("number").columns.tolist()
    cat = X.select_dtypes("category").columns.tolist()
    pre = ColumnTransformer([
        ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), num),
        ("cat", make_pipeline(SimpleImputer(strategy="most_frequent"),
                              OneHotEncoder(handle_unknown="ignore", min_frequency=5)), cat),
    ])
    est = Ridge(alpha=1.0) if task == "regression" else LogisticRegression(max_iter=2000, class_weight="balanced")
    return make_pipeline(pre, est)


def fix_cat(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Give b the same category set as a, so codes line up at predict time."""
    b = b.copy()
    for c in a.select_dtypes("category").columns:
        b[c] = pd.Categorical(b[c].astype("string"), categories=a[c].cat.categories)
    return b


def lgbm(task: str, n_classes: int):
    common = dict(n_estimators=2000, learning_rate=0.03, num_leaves=31, min_child_samples=20,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=SEED,
                  verbose=-1, n_jobs=-1)
    if task == "regression":
        return lgb.LGBMRegressor(**common)
    return lgb.LGBMClassifier(**common)


def split_gen(args, X, y, groups, order, task):
    if args.time:
        idx = np.argsort(order.values, kind="stable")
        for tr, va in TimeSeriesSplit(n_splits=args.folds).split(idx):
            yield idx[tr], idx[va]
    elif args.group:
        yield from GroupKFold(n_splits=args.folds).split(X, y, groups)
    elif task == "regression":
        yield from KFold(args.folds, shuffle=True, random_state=SEED).split(X)
    else:
        yield from StratifiedKFold(args.folds, shuffle=True, random_state=SEED).split(X, y)


def score(metric: str, y, pred, classes) -> float:
    if metric == "rmse":
        return root_mean_squared_error(y, pred)
    if metric == "mae":
        return mean_absolute_error(y, pred)
    if metric == "r2":
        return r2_score(y, pred)
    if metric == "logloss":
        return log_loss(y, pred, labels=classes)
    if metric == "auc":
        return roc_auc_score(y, pred[:, 1]) if len(classes) == 2 else roc_auc_score(
            y, pred, multi_class="ovr", labels=classes)
    if metric == "ap":
        return average_precision_score(y == classes[1], pred[:, 1])
    if metric == "f1":
        return f1_score(y, classes[(pred[:, 1] >= 0.5).astype(int)], pos_label=classes[1])
    if metric == "macro_f1":
        return f1_score(y, classes[pred.argmax(1)], average="macro")
    raise ValueError(metric)


def predict(model, X, task):
    return model.predict(X) if task == "regression" else model.predict_proba(X)


def fit_lgb(X, y, Xva, yva, task, n_classes, classes=None):
    if task == "classification":  # LightGBM needs integer labels for the eval set
        y, yva = np.searchsorted(classes, y), np.searchsorted(classes, yva)
    m = lgbm(task, n_classes)
    m.fit(X, y, eval_X=Xva, eval_y=yva, callbacks=[lgb.early_stopping(100, verbose=False)])
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("train")
    ap.add_argument("--target", required=True)
    ap.add_argument("--id", help="row id column (kept for the submission, not used as a feature)")
    ap.add_argument("--drop", nargs="*", default=[], help="columns to exclude, e.g. post-outcome fields")
    ap.add_argument("--time", help="timestamp column; switches to forward-chaining validation")
    ap.add_argument("--group", help="entity column; keeps each entity on one side of the split")
    ap.add_argument("--test", help="file to predict; writes submission.csv")
    ap.add_argument("--metric", help="auc ap f1 macro_f1 logloss rmse mae r2")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--out", default="outputs/baseline")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    charts.setup()

    df = load(args.train)
    for name, col in [("--target", args.target), ("--id", args.id), ("--time", args.time), ("--group", args.group)]:
        if col and col not in df.columns:
            sys.exit(f"{name} {col!r} is not a column. Columns: {list(df.columns)}")
    n0 = len(df)
    df = df[df[args.target].notna()].reset_index(drop=True)
    if len(df) < n0:
        print(f"Dropped {n0 - len(df):,} rows with a missing target")
    y = df[args.target]
    task = "regression" if pd.api.types.is_numeric_dtype(y) and y.nunique() > 20 else "classification"
    classes = np.array(sorted(y.unique())) if task == "classification" else None
    n_classes = len(classes) if classes is not None else 0
    metric = args.metric or ("rmse" if task == "regression" else "auc" if n_classes == 2 else "macro_f1")
    print(f"Task: {task}" + (f" ({n_classes} classes)" if n_classes else "") + f", metric: {metric}")

    order = pd.to_datetime(df[args.time], errors="coerce", format="mixed") if args.time else None
    groups = df[args.group] if args.group else None
    frame = time_features(df, args.time) if args.time else df
    X, removed = prepare(frame, [args.target, args.id, args.group, *args.drop])
    if removed:
        print(f"Skipped high-cardinality text columns (engineer these by hand): {removed}")
    print(f"Features: {X.shape[1]}")

    rows, oof_lgb = [], None
    importances = []
    y_arr = y.to_numpy()
    for name in ["dummy", "linear", "lightgbm"]:
        fold_scores = []
        oof = np.full(len(y), np.nan) if task == "regression" else np.full((len(y), n_classes), np.nan)
        for tr, va in split_gen(args, X, y, groups, order, task):
            Xtr, Xva = X.iloc[tr], fix_cat(X.iloc[tr], X.iloc[va])
            if name == "dummy":
                m = (DummyRegressor() if task == "regression" else DummyClassifier(strategy="prior")).fit(Xtr, y_arr[tr])
            elif name == "linear":
                m = linear_model(X, task).fit(Xtr, y_arr[tr])
            else:
                m = fit_lgb(Xtr, y_arr[tr], Xva, y_arr[va], task, n_classes, classes)
                importances.append(pd.Series(m.booster_.feature_importance("gain"), index=X.columns))
            p = predict(m, Xva, task)
            oof[va] = p
            fold_scores.append(score(metric, y_arr[va], p, classes))
        rows.append({"model": name, "mean": np.mean(fold_scores), "std": np.std(fold_scores)})
        print(f"  {name:9s} {metric} {np.mean(fold_scores):.4f} +/- {np.std(fold_scores):.4f}")
        if name == "lightgbm":
            oof_lgb = oof

    scores = pd.DataFrame(rows).set_index("model")
    scores.to_csv(out / "scores.csv")
    higher = metric in HIGHER_IS_BETTER
    best = scores["mean"].idxmax() if higher else scores["mean"].idxmin()
    delta = scores.loc[best, "mean"] - scores.loc["dummy", "mean"]
    fig, _ = charts.model_compare(scores, metric, f"Best: {best}, {delta:+.3f} {metric} vs dummy",
                                  f"{args.folds}-fold out-of-sample ({'right' if higher else 'left'} is better); bars show fold spread")
    charts.save(fig, "model_scores", out)

    imp = pd.concat(importances, axis=1).mean(axis=1).sort_values(ascending=False)
    imp = imp / imp.sum()
    imp.to_csv(out / "importance.csv", header=["gain_share"])
    fig, _ = charts.ranked_bars(imp.mul(100), title=f"{imp.index[0]} carries the most signal",
                                subtitle="LightGBM share of total gain (%). Association, not causation.",
                                top_n=15, fmt=lambda v: f"{v:.1f}%")
    charts.save(fig, "importance", out)
    if imp.iloc[0] > 0.6:
        print(f"WARNING: {imp.index[0]} has {imp.iloc[0]:.0%} of gain. Check it isn't leakage (recorded after the outcome?).")

    mask = ~np.isnan(oof_lgb if task == "regression" else oof_lgb[:, 0])
    best_t = 0.5
    if task == "classification":
        fig, _ = charts.confusion(y_arr[mask], classes[oof_lgb[mask].argmax(1)], labels=list(classes))
        charts.save(fig, "confusion", out)
        if n_classes == 2:
            pos = oof_lgb[mask, 1]
            yb = y_arr[mask] == classes[1]
            fig, _ = charts.calibration(yb, pos)
            charts.save(fig, "calibration", out)
            prec, rec, th = precision_recall_curve(yb, pos)
            f = 2 * prec * rec / np.clip(prec + rec, 1e-9, None)
            best_t = float(th[np.argmax(f[:-1])])
            print(f"Best-F1 threshold on out-of-fold: {best_t:.3f} (F1 {f[:-1].max():.4f}, vs {f1_score(yb, pos >= 0.5):.4f} at 0.5)")

    oof_df = pd.DataFrame({"row": np.where(mask)[0], "y_true": y_arr[mask]})
    if task == "regression":
        oof_df["pred"] = oof_lgb[mask]
    else:
        for i, c in enumerate(classes):
            oof_df[f"p_{c}"] = oof_lgb[mask, i]
    oof_df.to_csv(out / "oof_predictions.csv", index=False)

    if args.test:
        test = load(args.test)
        tframe = time_features(test, args.time) if args.time else test
        Xt, _ = prepare(tframe, [args.id, args.group, *args.drop])
        Xt = Xt.reindex(columns=X.columns)
        Xt = fix_cat(X, Xt)
        for c in X.select_dtypes("number").columns:
            Xt[c] = pd.to_numeric(Xt[c], errors="coerce")
        cut = int(len(X) * 0.9)
        idx = np.argsort(order.values, kind="stable") if args.time else np.random.RandomState(SEED).permutation(len(X))
        tr, va = idx[:cut], idx[cut:]
        m = fit_lgb(X.iloc[tr], y_arr[tr], fix_cat(X.iloc[tr], X.iloc[va]), y_arr[va], task, n_classes, classes)
        p = predict(m, Xt, task)
        sub = pd.DataFrame({args.id: test[args.id]} if args.id else {"row": np.arange(len(test))})
        if task == "regression":
            sub[args.target] = p
        elif n_classes == 2:
            sub[args.target] = p[:, 1]
            sub[f"{args.target}_label"] = classes[(p[:, 1] >= best_t).astype(int)]
        else:
            sub[args.target] = classes[p.argmax(1)]
        sub.to_csv(out / "submission.csv", index=False)
        print(f"Wrote {len(sub):,} predictions to {out / 'submission.csv'}. CHECK the required format against the challenge's sample.")

    if metric == "f1":
        print("Note: scoreboard F1 uses a 0.5 threshold and only the linear model is class-weighted, so compare models on the tuned F1 or AUC.")
    print(f"Saved to {out.resolve()}")


if __name__ == "__main__":
    main()
