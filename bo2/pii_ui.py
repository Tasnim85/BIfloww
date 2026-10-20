"""Local Streamlit job support; uses the existing PII CLI and contracts."""
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import pyarrow.parquet as pq

from convertir_parquet_csv import convertir
from privacy.models import PiiReport

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024


def validate_run_id(value):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", value):
        raise ValueError("Le nom du test doit contenir uniquement lettres, chiffres, tirets ou underscores.")
    return value


def validate_names(names):
    aliases = set()
    for name in names:
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
        if (not name or Path(name).name != name or any(char in name for char in '<>:"/\\|?*')
                or any(ord(char) < 32 for char in name) or name.rstrip(" .") != name
                or name.split(".")[0].upper() in reserved):
            raise ValueError("Chaque fichier doit avoir un nom simple, sans chemin.")
        path = Path(name)
        if path.suffix.lower() not in {".csv", ".parquet"}:
            raise ValueError("Seuls les fichiers CSV et Parquet sont acceptés.")
        alias = path.stem.removeprefix("olist_").removesuffix("_dataset").casefold()
        if alias in aliases:
            raise ValueError("Deux fichiers correspondent au même nom de table. Renommez-en un.")
        aliases.add(alias)
    if not aliases:
        raise ValueError("Sélectionnez au moins un fichier CSV ou Parquet.")


def local_dataset(value, root=ROOT):
    path = Path(value.strip().strip('"')).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.exists():
        raise ValueError("Le chemin du dataset est introuvable.")
    paths = [path] if path.is_file() else sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".parquet"})
    validate_names([p.name for p in paths])
    return path, len(paths)


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def table_preview(path, rows=100):
    parquet = pq.ParquetFile(path)
    batches = parquet.iter_batches(batch_size=rows)
    batch = next(batches, None)
    return batch.to_pandas() if batch is not None else parquet.schema_arrow.empty_table().to_pandas()


def csv_archive(pii_dir, *, summary=None):
    paths = sorted((pii_dir / "csv").glob("*.csv"))
    if not paths:
        raise ValueError("Générez les CSV avant de télécharger l’archive.")
    if sum(p.stat().st_size for p in paths) > MAX_DOWNLOAD_BYTES:
        raise ValueError("L’archive dépasse 128 Mo. Récupérez les CSV dans le dossier affiché.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, f"csv/{path.name}")
        if summary is None:
            archive.write(pii_dir / "pii_report.json", "pii_report.json")
        else:
            archive.writestr("bilan.txt", summary)
    return output.getvalue()


@dataclass
class Job:
    run_id: str
    process: subprocess.Popen
    log: Path
    started: float
    finalized: bool = False
    conversion_error: str | None = None
    finished: float | None = None


class JobManager:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.runs = self.root / "runs"
        self.jobs = {}
        self.lock = Lock()

    def run_dir(self, run_id):
        validate_run_id(run_id)
        return self.runs / run_id

    def history(self):
        if not self.runs.exists():
            return []
        return [p.name for p in sorted(self.runs.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                if p.is_dir() and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", p.name)
                and ((p / "pii/pii_report.json").exists() or p.name in self.jobs)]

    def active(self):
        return next((name for name, job in self.jobs.items() if job.process.poll() is None), None)

    def start(self, run_id, *, dataset=None, uploads=None, policy="review"):
        destination = self.run_dir(run_id)
        if policy not in {"review", "redact"}:
            raise ValueError("Mode d’incertitude invalide.")
        if uploads is not None:
            validate_names([name for name, _ in uploads])
            if sum(len(data) for _, data in uploads) > MAX_UPLOAD_BYTES:
                raise ValueError("Les fichiers importés dépassent 512 Mo au total.")
        else:
            dataset, _ = local_dataset(str(dataset or ""), self.root)
        with self.lock:
            if self.active():
                raise ValueError("Un test est déjà en cours. Attendez sa fin avant d’en lancer un autre.")
            if destination.exists():
                raise ValueError("Ce nom de test existe déjà. Choisissez un nouveau nom.")
            destination.mkdir(parents=True, exist_ok=False)
            if uploads is not None:
                dataset = destination / "inputs"
                dataset.mkdir()
                for name, data in uploads:
                    (dataset / name).write_bytes(data)
            log = destination / "pii_console.log"
            command = [sys.executable, "-u", "-m", "bo2", "step", "pii", "--dataset", str(dataset),
                       "--runs", str(self.runs), "--run-id", run_id, "--pii-uncertain", policy]
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
            with log.open("w", encoding="utf-8") as stream:
                process = subprocess.Popen(command, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.jobs[run_id] = Job(run_id, process, log, time.monotonic())
        return run_id

    def snapshot(self, run_id):
        job = self.jobs.get(run_id)
        directory = self.run_dir(run_id) / "pii"
        result = read_json(directory / "agent_result.json")
        running = job is not None and job.process.poll() is None
        if job and not running and not job.finalized:
            with self.lock:
                if not job.finalized:
                    if result and result.get("status") == "success":
                        try:
                            convertir(directory / "tables", directory / "csv")
                        except Exception as exc:
                            job.conversion_error = f"La conversion CSV a échoué ({type(exc).__name__}). Utilisez le bouton de conversion."
                    job.finalized = True
                    job.finished = time.monotonic()
        log_path = self.run_dir(run_id) / "pii_console.log"
        log = ""
        if log_path.exists():
            with log_path.open("rb") as stream:
                stream.seek(max(0, log_path.stat().st_size - 24000))
                log = stream.read().decode("utf-8", errors="replace")
        return {"running": running, "result": result, "log": log,
                "exit_code": job.process.poll() if job else None,
                "elapsed": int((job.finished or time.monotonic()) - job.started) if job else None,
                "conversion_error": job.conversion_error if job else None}

    def report(self, run_id):
        value = read_json(self.run_dir(run_id) / "pii/pii_report.json")
        return PiiReport.model_validate(value) if value else None
