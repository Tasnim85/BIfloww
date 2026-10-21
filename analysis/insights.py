"""Simple, deterministic insights computed from the result table. Every sentence carries its numbers
in `evidence`. (Step 6 will add the Groq agent that explores further and writes richer sentences.)"""
import pandas as pd

from contracts.analysis import Insight


def compute_insights(df: pd.DataFrame, dimensions: list[str], unit: str) -> list[Insight]:
    if not dimensions or df.empty:
        return []
    dim = dimensions[0]
    cur = df[df["period"] == "current"].groupby(dim)["value"].sum()
    out = []
    if cur.sum() > 0:
        top, total = cur.idxmax(), float(cur.sum())
        share = float(cur[top]) / total
        out.append(Insight(text=f"{top} makes {share:.0%} of the {unit} of the period.",
                           evidence={str(top): round(float(cur[top]), 2), "total": round(total, 2)}))
    prev = df[df["period"] == "previous"].groupby(dim)["value"].sum()
    if not prev.empty:
        delta = cur.subtract(prev, fill_value=0.0)
        mover = delta.abs().idxmax()
        out.append(Insight(
            text=f"{mover} moved the most: {float(delta[mover]):+,.2f} {unit} vs the previous period.",
            evidence={"current": round(float(cur.get(mover, 0.0)), 2),
                      "previous": round(float(prev.get(mover, 0.0)), 2),
                      "change": round(float(delta[mover]), 2)}))
    return out
