"""Project-local secrets, never printed or committed."""
import secrets
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_local():
    load_dotenv(ROOT / ".env", override=False)


def initialize() -> Path:
    path = ROOT / ".env"
    current = dotenv_values(path) if path.exists() else {}
    defaults = {"OLLAMA_BASE_URL": "http://127.0.0.1:11434", "OLLAMA_MODEL": "llama3:latest", "OLLAMA_TIMEOUT": "240", "OLLAMA_NUM_CTX": "4096", "NEO4J_URI": "bolt://127.0.0.1:7687", "NEO4J_USER": "neo4j", "NEO4J_DATABASE": "neo4j", "NEO4J_PASSWORD": secrets.token_urlsafe(32), "BO2_PII_SECRET": secrets.token_hex(32)}
    missing = {key: value for key, value in defaults.items() if not current.get(key)}
    if missing:
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n# BO2 local configuration\n")
            for key, value in missing.items():
                stream.write(f"{key}={value}\n")
    return path
