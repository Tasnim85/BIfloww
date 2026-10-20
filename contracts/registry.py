"""Which contract class describes which JSON output. "<step>.<output key>" -> class.

    from contracts.registry import read_output
    manifest = read_output(ctx.inputs["manifest"], "etl.manifest")
"""
from pathlib import Path

from contracts.analysis import AnalysisResult
from contracts.audit import IntegrityReport
from contracts.common import load
from contracts.comparisons import ComparisonReport
from contracts.dashboard import DashboardSpec
from contracts.intake import ColumnTypesReport, SimilarityReport, Upload
from contracts.privacy import PiiReport
from contracts.quality import AnomalyReport, CleaningReport, CoverageProfile, ProfileReport
from contracts.semantic import AnalysisRequest
from contracts.warehouse import LineageGraph, TransformationReceipts, WarehouseManifest
from contracts.xai import DriftReport, ExplanationReport

CONTRACT_OF = {
    "upload.upload": Upload,
    "similarity.report": SimilarityReport,
    "column_types.report": ColumnTypesReport,
    "pii.report": PiiReport,
    "profiling.profile": ProfileReport,
    "profiling.coverage": CoverageProfile,
    "profiling.anomalies": AnomalyReport,
    "cleaning.report": CleaningReport,
    "etl.manifest": WarehouseManifest,
    "etl.receipts": TransformationReceipts,
    "request.request": AnalysisRequest,
    "analysis.result": AnalysisResult,
    "comparisons.report": ComparisonReport,
    "dashboard.spec": DashboardSpec,
    "lineage.graph": LineageGraph,
    "auditor.explanations": ExplanationReport,
    "auditor.drift": DriftReport,
    "auditor.integrity": IntegrityReport,
}
# Outputs NOT in this table are data files, not JSON: tables/ folders (Parquet),
# warehouse.duckdb, anomaly_model.joblib, anomaly_scores.parquet, result.parquet.


def read_output(path: Path, ref: str):
    """Load and validate the output `ref` (e.g. "etl.manifest") stored at `path`."""
    return load(CONTRACT_OF[ref], path)
