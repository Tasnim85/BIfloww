"""tests/test_notebook.py — Verify notebook executability via nbclient.

Skips gracefully if nbclient or ipykernel are not installed.
"""
import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_PATH = REPO_ROOT / "intake" / "semantic_detection" / "notebooks" / "01_semantic_foundation.ipynb"
EXAMPLES_DIR = REPO_ROOT / "intake" / "semantic_detection" / "examples"


def test_notebook_exists():
    assert NOTEBOOK_PATH.exists(), f"Notebook not found: {NOTEBOOK_PATH}"


def test_notebook_is_valid_json():
    with open(NOTEBOOK_PATH, encoding='utf-8') as f:
        nb = json.load(f)
    assert nb.get('nbformat') == 4


def test_semantic_metadata_example_exists_and_valid():
    path = EXAMPLES_DIR / "semantic_metadata_example.json"
    assert path.exists()
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from contracts.proposals.semantic_contracts import SemanticMetadata
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    # Should parse without error
    SemanticMetadata.model_validate(data)


def test_taxonomy_validation_report_exists():
    path = EXAMPLES_DIR / "taxonomy_validation_report.json"
    assert path.exists()
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    assert data.get('valid') is True


@pytest.mark.skipif(
    not __import__('importlib').util.find_spec('nbclient'),
    reason="nbclient not installed"
)
def test_notebook_executes_without_errors():
    """Execute the notebook via nbclient and check for no cell errors."""
    import nbformat
    import nbclient
    with open(NOTEBOOK_PATH, encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)

    client = nbclient.NotebookClient(nb, timeout=120, kernel_name='python3')
    try:
        client.execute()
    except nbclient.exceptions.CellExecutionError as e:
        pytest.fail(f"Notebook cell execution error: {e}")

    # Check no output contains errors
    for cell in nb.cells:
        if cell.cell_type == 'code':
            for output in cell.get('outputs', []):
                assert output.get('output_type') != 'error', \
                    f"Cell error: {output.get('ename')}: {output.get('evalue')}"
