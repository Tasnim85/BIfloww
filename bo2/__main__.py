import argparse
import json
from pathlib import Path

from .demo import run_pipeline
from .sample import build
from .config import initialize, load_local


def main():
    load_local()
    parser = argparse.ArgumentParser(description="Ahmed & Ikbel BO2 tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-local", help="Initialize ignored .env without printing secrets")
    step = commands.add_parser("step", help="Run exactly one task without launching downstream tasks")
    step.add_argument("task", choices=["pii", "profiling", "cleaning", "etl", "lineage"])
    step.add_argument("--dataset", type=Path, default=Path("data/sample"))
    step.add_argument("--runs", type=Path, default=Path("runs"))
    step.add_argument("--run-id", required=True)
    step.add_argument("--schema", choices=["llm", "star", "snowflake", "constellation"], default="llm")
    step.add_argument("--warehouse-mode", choices=["dimensional", "generic", "auto", "olist"], default="dimensional")
    step.add_argument("--etl-approval", help="SHA256 of the reviewed warehouse_proposal.json")
    step.add_argument("--lineage-backend", choices=["neo4j", "json"], default="neo4j")
    step.add_argument("--pii-uncertain", choices=["review", "redact"], default="review")
    step.add_argument("--proposal", type=Path, help="Cleaning rules to review/apply")
    step.add_argument("--approval", type=Path, help="Human approval for the exact cleaning proposal")
    step.add_argument("--playbook", type=Path, help="Explicit cleaning playbook (otherwise select latest compatible)")
    step.add_argument("--profiling-task", choices=["all", "coverage", "anomalies"], default="all")
    sample = commands.add_parser("sample")
    sample.add_argument("--dataset", type=Path, default=Path("Dataset"))
    sample.add_argument("--output", type=Path, default=Path("data/sample"))
    sample.add_argument("--orders", type=int, default=500)
    demo = commands.add_parser("run")
    demo.add_argument("--dataset", type=Path, default=Path("data/sample"))
    demo.add_argument("--runs", type=Path, default=Path("runs"))
    demo.add_argument("--run-id", required=True)
    demo.add_argument("--schema", choices=["llm", "star", "snowflake", "constellation"], default="llm")
    demo.add_argument("--lineage-backend", choices=["neo4j", "json"], default="neo4j")
    demo.add_argument("--model", default=None)
    demo.add_argument("--workload", default=None)
    propose = commands.add_parser("propose")
    propose.add_argument("--profile", type=Path, required=True)
    propose.add_argument("--model", default="llama3:latest")
    propose.add_argument("--output", type=Path, required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("--proposal", type=Path, required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--output", type=Path, required=True)
    importing = commands.add_parser("lineage-import")
    importing.add_argument("--graph", type=Path, required=True)
    importing.add_argument("--run-id", required=True)
    query = commands.add_parser("lineage-query")
    query.add_argument("--run-id", required=True)
    query.add_argument("--target", default="kpi:Revenue_demo")
    args = parser.parse_args()
    if args.command == "init-local":
        print(f"Local configuration initialized: {initialize()} (secrets not displayed)")
    elif args.command == "step":
        from .steps import run_step
        result = run_step(args.task, args.dataset, args.runs, args.run_id, schema_mode=args.schema, backend=args.lineage_backend, pii_uncertain=args.pii_uncertain, proposal=args.proposal, approval=args.approval, playbook=args.playbook, profiling_task=args.profiling_task, warehouse_mode=args.warehouse_mode, etl_approval=args.etl_approval)
        print(result.model_dump_json(indent=2))
        raise SystemExit(0 if result.status.value == "success" else 2)
    elif args.command == "sample":
        print(json.dumps(build(args.dataset, args.output, args.orders), indent=2))
    elif args.command == "run":
        result = run_pipeline(args.dataset, args.runs, args.run_id, schema_mode=args.schema, lineage_backend=args.lineage_backend, llm_model=args.model, workload=args.workload)
        raise SystemExit(0 if result["status"] == "success" else 2)
    elif args.command == "propose":
        from cleaning.llm_rules import generate
        # Whitelist metadata: an arbitrary JSON profile cannot exfiltrate samples.
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        metadata = {"tables": {table: {"rows": values["rows"], "columns": {column: {key: stats[key] for key in ("dtype", "missing", "distinct")} for column, stats in values["columns"].items()}} for table, values in profile["tables"].items()}}
        print(generate(metadata, args.model, args.output))
    elif args.command == "approve":
        from cleaning.llm_rules import approve as approve_proposal
        print(approve_proposal(args.proposal, args.reviewer, args.output))
    elif args.command == "lineage-import":
        from etl.models import LineageReport
        from etl.neo4j_store import import_graph
        graph = LineageReport.model_validate_json(args.graph.read_text(encoding="utf-8"))
        report = import_graph(graph, args.run_id)
        args.graph.with_name("neo4j_import.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    else:
        from etl.neo4j_store import ancestors
        print(json.dumps(ancestors(args.run_id, args.target), indent=2))


if __name__ == "__main__":
    main()
