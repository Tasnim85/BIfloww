"""Copy the example run and static files where the pipeline expects them.

    python -m contracts.examples.install

  contracts/examples/run_001/  ->  runs/run_001/        (fake outputs of every step)
  contracts/examples/static/   ->  kpi/, semantic/, cleaning/playbooks/
Existing files are NEVER overwritten: your own work stays untouched.
"""
import shutil
from pathlib import Path

from contracts.pipeline import REPO_ROOT, RUNS_ROOT

HERE = Path(__file__).parent


def _copy_tree(src: Path, dst: Path) -> int:
    n = 0
    for f in src.rglob("*"):
        target = dst / f.relative_to(src)
        if f.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            n += 1
    return n


if __name__ == "__main__":
    a = _copy_tree(HERE / "run_001", REPO_ROOT / RUNS_ROOT / "run_001")
    b = _copy_tree(HERE / "static", REPO_ROOT)
    print(f"{a} files copied into runs/run_001/, {b} static files copied (existing files kept).")
