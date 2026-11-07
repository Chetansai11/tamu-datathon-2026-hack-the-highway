"""Static chart helpers for slides and write-ups (matplotlib).

Rules these helpers enforce so you don't have to think about them at 4 AM:
  - one axis only (never a dual axis)
  - colour follows the entity, assigned in a fixed order
  - past 7 series the tail folds into "Other"
  - single series = one colour; emphasis = highlight one, grey the rest
  - legend for 2+ series, direct end labels when there are 4 or fewer
  - recessive hairline grid, thin marks

Write the TAKEAWAY as the title ("Late orders cost $12k a month"), not the
topic ("Orders by month"). Every function returns (fig, ax).

    from charts import setup, ranked_bars, save
    setup()
    fig, ax = ranked_bars(s, title="Three items drive 60% of waste")
    save(fig, "waste_by_item")
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=False)
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter
import pandas as pd

# Validated categorical order: adjacent pairs clear the colour-blind separation
# target. Scatter plots may only use the first 3 (see scatter()).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
OTHER = "#c3c2b7"
DIVERGING_NEG = "#e34948"
DIVERGING_MID = "#f0efec"
DIVERGING_POS = "#2a78d6"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

OUT_DIR = Path("outputs/charts")


def setup() -> None:
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 220,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Arial", "DejaVu Sans"],
        "font.size": 11, "text.color": INK,
        "axes.edgecolor": BASELINE, "axes.linewidth": 0.8,
        "axes.labelcolor": INK_2, "axes.labelsize": 10,
        "axes.titlesize": 14, "axes.titleweight": "semibold", "axes.titlelocation": "left",
        "axes.titlepad": 14,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.axisbelow": True,
        "grid.color": GRID, "grid.linewidth": 0.7, "grid.linestyle": "-",
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelsize": 9.5, "ytick.labelsize": 9.5,
        "xtick.major.size": 0, "ytick.major.size": 0,
        "lines.linewidth": 2, "lines.markersize": 7,
        "legend.frameon": False, "legend.fontsize": 9.5, "legend.labelcolor": INK_2,
    })


def save(fig, name: str, out_dir: str | Path | None = None) -> Path:
    d = Path(out_dir) if out_dir else OUT_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.png"
    fig.savefig(path, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    return path


def _title(ax, title, subtitle=None):
    if subtitle:
        ax.set_title(title, pad=30)
        ax.text(0, 1.03, subtitle, transform=ax.transAxes, color=INK_2, fontsize=10, va="bottom")
    else:
        ax.set_title(title)


def _short(v) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.1f}B"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e3:
        return f"{v / 1e3:.1f}".rstrip("0").rstrip(".") + "k"
    if a >= 100 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:.2f}"


AXIS_FMT = FuncFormatter(lambda v, _: _short(v))


def _date_axis(ax, x_values, ticks: int = 7) -> None:
    if pd.api.types.is_datetime64_any_dtype(pd.Series(x_values)):
        loc = mdates.AutoDateLocator(maxticks=ticks)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))


def complete_periods(df: pd.DataFrame, date: str, freq: str = "W") -> pd.DataFrame:
    """Add a `period` column and drop a partial first or last period.

    A half-filled final week otherwise plots as a sudden crash. freq: D, W, M, Q.
    """
    t = pd.to_datetime(df[date])
    out = df.assign(period=t.dt.to_period(freq).dt.start_time)
    days = t.dt.normalize().groupby(out["period"]).nunique()
    partial = [p for p in (days.index.min(), days.index.max()) if days[p] < 0.9 * days.median()]
    return out[~out["period"].isin(partial)]


def fold_other(df: pd.DataFrame, series: str, value: str, keep: int = 7):
    """Keep the `keep` biggest series; roll the rest into 'Other'."""
    order = df.groupby(series, observed=True)[value].sum().sort_values(ascending=False)
    top = list(order.index[:keep])
    out = df.copy()
    out[series] = out[series].where(out[series].isin(top), "Other").astype(str)
    return out, [str(t) for t in top]


def ranked_bars(s: pd.Series, title: str, subtitle=None, highlight=None, top_n: int = 12,
                fmt=_short, xlabel=None):
    """Compare a measure across unordered categories. s: index=label, value=measure."""
    s = s.dropna().sort_values(ascending=False)
    if len(s) > top_n:
        rest = s.iloc[top_n - 1:].sum()
        n_rest = len(s) - top_n + 1
        s = pd.concat([s.iloc[: top_n - 1], pd.Series({f"Other ({n_rest})": rest})])
    s = s.iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, max(2.4, 0.42 * len(s) + 1.2)))
    colors = [SERIES[0] if highlight is None or str(i) == str(highlight) else OTHER for i in s.index]
    ax.barh([str(i) for i in s.index], s.values, color=colors, height=0.55)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", labelcolor=INK_2)
    span = max(abs(s.max()), abs(s.min()), 1e-12)
    for lab in (0, len(s) - 1):
        v = s.values[lab]
        ax.text(v + span * 0.012, lab, fmt(v), va="center", fontsize=9.5, color=INK_2)
    ax.xaxis.set_major_formatter(AXIS_FMT)
    if xlabel:
        ax.set_xlabel(xlabel)
    _title(ax, title, subtitle)
    return fig, ax


def lines(df: pd.DataFrame, x: str, y: str, title: str, series: str | None = None, subtitle=None,
          ylabel=None, zero_base: bool = False):
    """Change over time. Long-format df; pass `series` for multiple lines."""
    fig, ax = plt.subplots(figsize=(9, 4.4))
    if series is None:
        d = df.groupby(x, observed=True)[y].sum().sort_index()
        ax.plot(d.index, d.values, color=SERIES[0])
    else:
        d, top = fold_other(df, series, y)
        names = top + (["Other"] if (d[series] == "Other").any() else [])
        label_ends = len(names) <= 4
        for i, name in enumerate(names):
            g = d[d[series] == name].groupby(x, observed=True)[y].sum().sort_index()
            color = OTHER if name == "Other" else SERIES[i]
            ax.plot(g.index, g.values, color=color, label=name)
            if label_ends:
                ax.annotate(name, (g.index[-1], g.values[-1]), xytext=(6, 0),
                            textcoords="offset points", va="center", fontsize=9.5, color=INK_2,
                            annotation_clip=False)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=min(len(names), 4))
    if zero_base:
        ax.set_ylim(bottom=0)
    ax.grid(axis="x", visible=False)
    ax.yaxis.set_major_formatter(AXIS_FMT)
    _date_axis(ax, df[x])
    if ylabel:
        ax.set_ylabel(ylabel)
    _title(ax, title, subtitle)
    return fig, ax


def distribution(s: pd.Series, title: str, subtitle=None, bins: int = 40, xlabel=None):
    s = pd.to_numeric(s, errors="coerce").dropna()
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.hist(s, bins=bins, color=SERIES[0], rwidth=0.9)
    med = float(s.median())
    ax.axvline(med, color=INK_2, lw=1)
    ax.text(med, ax.get_ylim()[1], f" median {_short(med)}", color=INK_2, fontsize=9.5, va="top")
    ax.grid(axis="x", visible=False)
    if xlabel:
        ax.set_xlabel(xlabel)
    _title(ax, title, subtitle)
    return fig, ax


def small_multiples(df: pd.DataFrame, x: str, y: str, facet: str, title: str, max_panels: int = 8,
                    subtitle=None):
    """Use instead of a dual axis or a spaghetti chart. Panels share one y scale."""
    order = df.groupby(facet, observed=True)[y].sum().sort_values(ascending=False).index[:max_panels]
    n = len(order)
    cols = min(n, 4)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(2.9 * cols, 2.4 * rows + 0.8), sharex=True,
                             sharey=True, squeeze=False)
    for ax in axes.flat[n:]:
        ax.set_visible(False)
    for ax, name in zip(axes.flat, order):
        g = df[df[facet] == name].groupby(x, observed=True)[y].sum().sort_index()
        ax.plot(g.index, g.values, color=SERIES[0], lw=1.8)
        ax.set_title(str(name), fontsize=10.5, fontweight="normal", color=INK_2, pad=6)
        ax.grid(axis="x", visible=False)
        ax.yaxis.set_major_formatter(AXIS_FMT)
        _date_axis(ax, df[x], ticks=4)
    fig.suptitle(title, x=0.01, y=0.995, ha="left", fontsize=14, fontweight="semibold", color=INK)
    if subtitle:
        fig.text(0.01, 1 - 0.5 / fig.get_figheight(), subtitle, color=INK_2, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 1 - (0.55 if subtitle else 0.35) / fig.get_figheight()))
    return fig, axes


def scatter(df: pd.DataFrame, x: str, y: str, title: str, hue: str | None = None, subtitle=None,
            sample: int = 5000):
    """Relationship between two measures. Hue is capped at 3 groups + Other, because
    past 3 the palette can't stay colour-blind safe for overlapping points."""
    d = df[[c for c in (x, y, hue) if c]].dropna()
    if len(d) > sample:
        d = d.sample(sample, random_state=0)
    fig, ax = plt.subplots(figsize=(7.5, 5))
    if hue is None:
        ax.scatter(d[x], d[y], s=22, color=SERIES[0], alpha=0.55, linewidths=0)
    else:
        order = d[hue].value_counts()
        top = list(order.index[:3])
        rest = d[~d[hue].isin(top)]
        if len(rest):
            ax.scatter(rest[x], rest[y], s=14, color=OTHER, alpha=0.4, linewidths=0, label="Other")
        for i, name in enumerate(top):
            g = d[d[hue] == name]
            ax.scatter(g[x], g[y], s=16, color=SERIES[i], alpha=0.45, linewidths=0, label=str(name))
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, markerscale=1.3)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    _title(ax, title, subtitle)
    return fig, ax


def _diverging_cmap():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("rb", [DIVERGING_NEG, DIVERGING_MID, DIVERGING_POS])


def corr_heatmap(df: pd.DataFrame, title: str = "How numeric columns move together", max_cols: int = 14):
    d = df.select_dtypes("number")
    d = d.loc[:, d.nunique() > 1]
    if d.shape[1] > max_cols:
        d = d[d.var().sort_values(ascending=False).index[:max_cols]]
    c = d.corr()
    n = len(c)
    fig, ax = plt.subplots(figsize=(0.62 * n + 2.6, 0.55 * n + 1.8))
    shown = c.values.copy()
    np.fill_diagonal(shown, np.nan)  # self-correlation is always 1 and only adds noise
    cmap = _diverging_cmap()
    cmap.set_bad(SURFACE)
    im = ax.imshow(shown, cmap=cmap, vmin=-1, vmax=1)
    ax.set_xticks(range(n), c.columns, rotation=45, ha="right")
    ax.set_yticks(range(n), c.index)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    for i in range(n):
        for j in range(n):
            if i != j and abs(c.values[i, j]) >= 0.5:  # label only what matters
                ax.text(j, i, f"{c.values[i, j]:.2f}", ha="center", va="center", fontsize=8,
                        color="#ffffff" if abs(c.values[i, j]) > 0.75 else INK)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.03)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=8.5)
    ax.set_title(title)
    return fig, ax


def stat_tiles(stats: dict[str, str], title: str | None = None):
    """When the answer is one number, show the number, not a chart."""
    n = len(stats)
    fig, axes = plt.subplots(1, n, figsize=(2.9 * n, 1.9), squeeze=False)
    for ax, (label, value) in zip(axes[0], stats.items()):
        ax.axis("off")
        ax.text(0, 0.62, str(value), fontsize=26, fontweight="semibold", color=INK, va="center")
        ax.text(0, 0.22, label, fontsize=10.5, color=INK_2, va="center")
    if title:
        fig.suptitle(title, x=0.02, ha="left", fontsize=14, fontweight="semibold")
    fig.tight_layout()
    return fig, axes


# --- model diagnostics -------------------------------------------------------

def model_compare(scores: pd.DataFrame, metric: str, title: str, subtitle=None):
    """scores: index=model, columns mean, std. Dots with spread: shows when a 'win' is noise."""
    s = scores.sort_values("mean")
    fig, ax = plt.subplots(figsize=(7.5, 0.6 * len(s) + 1.6))
    y = np.arange(len(s))
    ax.errorbar(s["mean"], y, xerr=s["std"].fillna(0), fmt="o", color=SERIES[0], ecolor=BASELINE,
                elinewidth=2, markersize=8, capsize=0)
    ax.set_yticks(y, s.index)
    ax.tick_params(axis="y", labelcolor=INK_2)
    ax.margins(y=0.25)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(metric)
    _title(ax, title, subtitle)
    return fig, ax


def confusion(y_true, y_pred, title: str = "Where the model is wrong", labels=None):
    from sklearn.metrics import confusion_matrix
    labels = labels if labels is not None else sorted(pd.unique(pd.Series(y_true)))
    m = confusion_matrix(y_true, y_pred, labels=labels)
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    n = len(labels)
    fig, ax = plt.subplots(figsize=(1.0 * n + 2.6, 0.9 * n + 1.7))
    ax.imshow(m, cmap=cmap)
    ax.set_xticks(range(n), labels)
    ax.set_yticks(range(n), labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    thresh = m.max() * 0.55
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{m[i, j]:,}", ha="center", va="center", fontsize=10,
                    color="#ffffff" if m[i, j] > thresh else INK)
    ax.set_title(title)
    return fig, ax


def calibration(y_true, y_prob, title: str = "Do predicted probabilities match reality?", bins: int = 10):
    from sklearn.calibration import calibration_curve
    frac, mean = calibration_curve(y_true, y_prob, n_bins=bins, strategy="quantile")
    fig, ax = plt.subplots(figsize=(5.2, 5))
    ax.plot([0, 1], [0, 1], color=BASELINE, lw=1)
    ax.plot(mean, frac, color=SERIES[0], marker="o")
    ax.text(0.97, 0.9, "perfect", color=MUTED, fontsize=9.5, ha="right")
    ax.set_xlabel("Predicted probability")
    ax.set_ylabel("Observed rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title(title)
    return fig, ax
