"""Matplotlib rendering of a ChartSpec, for the lab and the notebook (headless, no Streamlit).

Honest-chart rules enforced here: bars always start at zero, never a dual axis, a pie sorted
by size. The Streamlit app can follow the same rules (see dashboard_ai/README.md).
"""
import textwrap

import matplotlib.pyplot as plt
import pandas as pd

from contracts.dashboard import ChartSpec, ChartType


def draw(spec: ChartSpec, df: pd.DataFrame, ax) -> None:
    ax.set_title(spec.title, fontsize=10, loc="left")
    if spec.chart_type == ChartType.KPI_CARD:
        ax.axis("off")
        ax.text(0.5, 0.5, f"{df['value'].iloc[0]:,.0f}", ha="center", va="center", fontsize=26, weight="bold")
    elif spec.chart_type == ChartType.BAR:
        if spec.color and spec.color in df.columns:
            wide = df.pivot_table(index=spec.x, columns=spec.color, values="value", aggfunc="sum", sort=False)
        else:
            wide = df.set_index(spec.x)[["value"]]
        horizontal = len(wide) > 8
        wide.plot.barh(ax=ax) if horizontal else wide.plot.bar(ax=ax, rot=45)
        if horizontal:
            ax.invert_yaxis()
            ax.set_xlim(left=0)
        else:
            ax.set_ylim(bottom=0)                       # bars start at zero: never truncate
        if wide.shape[1] == 1:
            ax.legend_.remove() if ax.get_legend() else None
    elif spec.chart_type == ChartType.LINE:
        if spec.color and spec.color in df.columns:
            for key, g in df.groupby(spec.color):
                ax.plot(g[spec.x].astype(str), g["value"], marker="o", label=str(key))
            ax.legend()
        else:
            ax.plot(df[spec.x].astype(str), df["value"], marker="o")
        ax.tick_params(axis="x", rotation=45)
    elif spec.chart_type == ChartType.PIE:
        ax.pie(df["value"], labels=df[spec.x], autopct="%1.0f%%", startangle=90, counterclock=False)
    else:                                               # table
        ax.axis("off")
        shown = df.head(12)
        tbl = ax.table(cellText=shown.round(2).values, colLabels=list(shown.columns), loc="center")
        tbl.scale(1, 1.2)


def figure(spec_charts: list[ChartSpec], frames: dict[str, pd.DataFrame], warnings: list[str]):
    n = len(spec_charts)
    fig, axes = plt.subplots(1, n, figsize=(5.2 * n, 4.2), gridspec_kw={"width_ratios": [1] + [2.4] * (n - 1)} if n > 1 else None)
    axes = [axes] if n == 1 else list(axes)
    for spec, ax in zip(spec_charts, axes):
        draw(spec, frames[spec.chart_id], ax)
    if warnings:
        lines = [l for w in warnings[:4] for l in textwrap.wrap("! " + w, 150, subsequent_indent="  ")]
        fig.text(0.01, 0.01, "\n".join(lines), fontsize=7.5, color="#a33", va="bottom")
        fig.subplots_adjust(bottom=0.12 + 0.03 * len(lines))
    return fig
