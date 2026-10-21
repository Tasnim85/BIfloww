"""Transactional, idempotent lineage imports scoped to a BIFlow run."""
import hashlib
import json
import os

from neo4j import GraphDatabase

from .models import LineageReport


def settings():
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        raise ValueError("Set NEO4J_PASSWORD in the ignored project .env (python -m bo2 init-local)")
    return {"uri": os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"), "user": os.environ.get("NEO4J_USER", "neo4j"), "password": password, "database": os.environ.get("NEO4J_DATABASE", "neo4j")}


def _write_graph(tx, run_id, graph, graph_hash):
    record = tx.run("MERGE (r:BIFlowRun {run_id: $run_id}) ON CREATE SET r.graph_hash=$graph_hash RETURN r.graph_hash AS graph_hash", run_id=run_id, graph_hash=graph_hash).single()
    if record["graph_hash"] != graph_hash:
        raise ValueError("This Neo4j run_id already contains a different graph; choose a new run_id")
    tx.run("UNWIND $nodes AS n MERGE (v:BIFlowLineage {run_id:$run_id, node_id:n.id}) SET v.kind=n.kind", run_id=run_id, nodes=graph["nodes"]).consume()
    tx.run("UNWIND $edges AS e MATCH (s:BIFlowLineage {run_id:$run_id, node_id:e.source}) MATCH (t:BIFlowLineage {run_id:$run_id, node_id:e.target}) MERGE (s)-[:DERIVES {run_id:$run_id, operation:e.operation}]->(t)", run_id=run_id, edges=graph["edges"]).consume()
    nodes = tx.run("MATCH (n:BIFlowLineage {run_id:$run_id}) RETURN count(n) AS total", run_id=run_id).single()["total"]
    edges = tx.run("MATCH (:BIFlowLineage {run_id:$run_id})-[r:DERIVES {run_id:$run_id}]->(:BIFlowLineage {run_id:$run_id}) RETURN count(r) AS total", run_id=run_id).single()["total"]
    if nodes != len(graph["nodes"]) or edges != len(graph["edges"]):
        raise ValueError("Neo4j node/edge counts do not match the graph; rolling back")
    return {"nodes": nodes, "edges": edges}


def import_graph(graph: LineageReport, run_id: str) -> dict:
    data = graph.model_dump(mode="json")
    if "contract_version" in data:
        data={"nodes":[{"id":n["id"],"kind":n["kind"]} for n in data["nodes"]],
              "edges":[{"source":e["source"],"target":e["target"],"operation":e["relation"]} for e in data["edges"]]}
    ids = [n["id"] for n in data["nodes"]]
    if len(ids) != len(set(ids)) or any(e["source"] not in ids or e["target"] not in ids for e in data["edges"]):
        raise ValueError("Invalid graph: duplicate nodes or dangling edges")
    if len({(e["source"], e["target"], e["operation"]) for e in data["edges"]}) != len(data["edges"]):
        raise ValueError("Invalid graph: duplicate edges")
    canonical = {"nodes": sorted(data["nodes"], key=lambda n: n["id"]), "edges": sorted(data["edges"], key=lambda e: (e["source"], e["target"], e["operation"]))}
    graph_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    config = settings()
    with GraphDatabase.driver(config["uri"], auth=(config["user"], config["password"]), connection_timeout=5, max_transaction_retry_time=10) as driver:
        driver.verify_connectivity()
        with driver.session(database=config["database"]) as session:
            session.run("CREATE CONSTRAINT biflow_lineage_node IF NOT EXISTS FOR (n:BIFlowLineage) REQUIRE (n.run_id,n.node_id) IS UNIQUE").consume()
            session.run("CREATE CONSTRAINT biflow_lineage_run IF NOT EXISTS FOR (r:BIFlowRun) REQUIRE r.run_id IS UNIQUE").consume()
            counts = session.execute_write(_write_graph, run_id, data, graph_hash)
    return {"status": "success", "run_id": run_id, "uri": config["uri"], "database": config["database"], "graph_sha256": graph_hash, **counts}


def ancestors(run_id: str, target: str) -> list[dict]:
    config = settings()
    with GraphDatabase.driver(config["uri"], auth=(config["user"], config["password"]), connection_timeout=5) as driver:
        with driver.session(database=config["database"]) as session:
            result = session.run("MATCH (source:BIFlowLineage {run_id:$run_id})-[:DERIVES*0..20]->(target:BIFlowLineage {run_id:$run_id, node_id:$target}) RETURN DISTINCT source.node_id AS node_id, source.kind AS kind ORDER BY node_id", run_id=run_id, target=target)
            return [record.data() for record in result]
