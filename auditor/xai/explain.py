"""Builds the Auditor's ExplanationReport from the profiling outputs.

    python -m auditor.xai.explain                 # run_001, all anomalies + 20 normal rows
    python -m auditor.xai.explain --run run_001 --normal 50

The Auditor NEVER changes a decision: is_anomaly and anomaly_score are copied
from the profiler. It only explains them. The step-4 agent will call build_report().
"""
import argparse
from pathlib import Path

import numpy as np

from auditor.xai.narrator import narrate_parts
from auditor.xai.shap_explainer import (build_explainer, explain_rows, load_profiling,
                                        path_length_to_score)
from contracts.common import save
from contracts.i18n import render
from contracts.pipeline import context_for, output_path
from contracts.xai import AnomalyExplanation, ExplanationReport, FeatureContribution


def build_report(anomalies: Path, model: Path, scores: Path,
                 n_normal: int = 20, seed: int = 0) -> ExplanationReport:
    prof = load_profiling(anomalies, model, scores)
    key = prof.report.row_key
    s = prof.scores.set_index(key)

    # Rows to explain: every anomaly (most anomalous first) + a random sample of normal rows
    flagged = s[s["is_anomaly"]].sort_values("anomaly_score", ascending=False).index
    normal = s[~s["is_anomaly"]].sample(n=min(n_normal, int((~s["is_anomaly"]).sum())),
                                        random_state=seed).index
    rows = flagged.append(normal)

    X_all = prof.X_model          # what the trees see (after the profiler's preprocessing, if any)
    medians = X_all.median()
    explainer = build_explainer(prof.model)
    explanations = explain_rows(explainer, X_all.loc[rows])

    out = []
    for key, exp in zip(rows, explanations):          # the original key: row keys can be integers
        decision = bool(s.at[key, "is_anomaly"])
        score = float(s.at[key, "anomaly_score"])
        out.append(AnomalyExplanation(
            row_key=exp.row_key, is_anomaly=decision, anomaly_score=round(score, 6),
            base_value=round(exp.base_value, 6), model_output=round(exp.model_output, 6),
            contributions=[FeatureContribution(feature=r.feature, value=float(r.value),
                                               shap_value=round(float(r.shap_value), 6))
                           for r in exp.sorted_contributions().itertuples()],
            narrative=render(parts := narrate_parts(exp, decision, medians, labels=prof.report.feature_labels,
                                                    units=prof.report.feature_units)),
            narrative_parts=parts))

    # Guarantee: SHAP explains EXACTLY the score that took the decision
    rebuilt = np.array([path_length_to_score(e.model_output, prof.estimator.max_samples_)
                        for e in explanations])
    actual = s.loc[rows, "anomaly_score"].to_numpy()
    worst = float(np.max(np.abs(rebuilt - actual)))
    if worst > 1e-6:
        raise AssertionError(f"SHAP does not reproduce the profiler's scores (max gap {worst:.2e})")

    return ExplanationReport(table=prof.report.table, model_version=prof.report.model_version,
                             explainer="shap.TreeExplainer", explanations=out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="run_001")
    p.add_argument("--normal", type=int, default=20, help="normal rows explained for comparison")
    args = p.parse_args()

    ctx = context_for("auditor", args.run)
    report = build_report(ctx.inputs["anomalies"], ctx.inputs["model"], ctx.inputs["scores"],
                          n_normal=args.normal)
    path = save(report, output_path(args.run, "auditor", "explanations"))

    n_anom = sum(e.is_anomaly for e in report.explanations)
    print(f"OK {len(report.explanations)} rows explained ({n_anom} anomalies, "
          f"{len(report.explanations) - n_anom} normal) -> {path}")
    print("OK SHAP reproduces the profiler's score for every row (gap < 1e-6)")
    print("\nMost anomalous payment:")
    print("  ", report.explanations[0].narrative)
    normal = next(e for e in report.explanations if not e.is_anomaly)
    print("A normal payment:")
    print("  ", normal.narrative)


if __name__ == "__main__":
    main()
