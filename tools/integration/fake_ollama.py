"""TEST DOUBLE for a local Ollama (llama3) — integration testing only, never a real model.
Answers BO2's PII prompts deterministically from Malek's column types, so the data flow
pii -> profiling -> cleaning -> etl -> analysis -> comparisons -> auditor can be checked here."""
import json, os
SCENARIO = os.environ.get("FAKE_SCENARIO", "ideal")   # ideal | orders_fact | star | drop_links | pii_unsure
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAP = {"ID": "INTERNAL_KEY", "EMAIL": "EMAIL", "PHONE": "PHONE", "PERSON_NAME": "PERSON_NAME", "AGE": "AGE",
       "AMOUNT": "MEASURE", "QUANTITY": "MEASURE", "NUMBER": "MEASURE", "DATE": "TIMESTAMP", "DATETIME": "TIMESTAMP",
       "CITY": "ADDRESS", "STATE": "CATEGORY", "ZIP_CODE": "POSTAL_CODE", "CATEGORY": "CATEGORY", "TEXT": "FREE_TEXT",
       "BOOLEAN": "CATEGORY", "OTHER": "UNKNOWN"}
PERSON_KEYS = {"customer_unique_id"}

def by_name(col, examples):
    # PII never receives Malek's hints (table names differ), so decide from the name like a model would
    w = set(col.split("_"))
    if col.endswith("_id") or w & {"id"}: return "INTERNAL_KEY"
    if w & {"zip", "postal"}: return "POSTAL_CODE"
    if "city" in w: return "ADDRESS"
    if w & {"comment", "message", "title"}: return "FREE_TEXT"
    if w & {"date", "timestamp", "at"}: return "TIMESTAMP"
    try:
        [float(e) for e in examples]; return "MEASURE" if examples else "CATEGORY"
    except ValueError:
        return "CATEGORY"

def column_answer(desc):
    hint = desc.get("upstream_hint") or {}
    col = desc["column"].lstrip("﻿").lower()
    if "lat" in col.split("_") or "lng" in col.split("_"): kind = "COORDINATE"
    elif col in PERSON_KEYS: kind = "PERSONAL_ID"
    elif hint: kind = MAP.get(hint.get("semantic_type", "OTHER"), "UNKNOWN")
    else: kind = by_name(col, desc.get("examples_local_only", []))
    conf = 0.6 if SCENARIO == "pii_unsure" and kind in ("CATEGORY", "MEASURE") and "state" in col else 0.95
    return {"semantic_type": kind, "confidence": conf}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.endswith("/api/tags"):
            data = json.dumps({"models": [{"name": "llama3:latest", "model": "llama3:latest"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        meta = json.loads(body["messages"][-1]["content"])
        if "columns" in meta:                                   # column batch or single attribute review
            out = {k: column_answer(d) for k, d in meta["columns"].items()}
        elif "keys" in meta:                                    # key entity refinement
            out = {k: {"semantic_type": "PERSONAL_ID" if v["column"].lower() in PERSON_KEYS else "INTERNAL_KEY", "confidence": 0.95}
                   for k, v in meta["keys"].items()}
        elif body["format"].get("title") == "Labels":           # ETL: role of each table
            def role(name, info):
                src = str(info.get("source", name)).lower()
                if "translation" in src: return "reference"
                if SCENARIO == "orders_fact" and src == "orders": return "fact"
                if any(k in src for k in ("payment", "item", "review")): return "fact"
                return "dimension"
            out = {"tables": [{"table": n, "role": role(n, i), "grain": "une ligne par enregistrement",
                               "reason": "rôle déduit des colonnes et des références"} for n, i in meta["tables"].items()]}
        elif body["format"].get("title") == "RelationshipDecisions":   # ETL: keep every verified link
            keys = list(body["format"]["properties"])
            # drop_links: a cautious model refuses some verified links (here: every second one)
            out = {k: (i % 2 == 0 if SCENARIO == "drop_links" else True) for i, k in enumerate(keys)}
            if SCENARIO == "drop_payment_link":       # the model refuses payments -> orders
                cands = meta["candidates"]
                out = {c["id"]: not ("payment" in c.get("child_source", "") and c.get("parent_source") == "orders") for c in cands}
        elif body["format"].get("title") == "LayoutDecision":          # ETL: layout
            allowed = body["format"]["$defs"]["SupportedLayout"]["enum"]
            want = "star" if SCENARIO == "star" else "constellation"
            out = {"schema_type": want if want in allowed else allowed[0],
                   "rationale": "Dimensions partagées entre faits, grain des lignes préservé."}
        else:
            self.send_response(500); self.end_headers(); self.wfile.write(b'{"error":"fake ollama: unknown prompt"}'); return
        data = json.dumps({"done": True, "done_reason": "stop", "message": {"role": "assistant", "content": json.dumps(out)}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(data)

def run_server(port=11434):
    server = ThreadingHTTPServer(("127.0.0.1", port), H)
    server.serve_forever()

if __name__ == "__main__":
    run_server()
