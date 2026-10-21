"""The prompt registry: prompts live in prompts/*.yaml, with a version and a changelog."""
import pytest
import yaml
from pydantic import ValidationError

from contracts.prompts import load_prompt


def write(folder, name, **override):
    data = {"name": name, "version": "1.1", "owner": "Tasnim", "used_by": "x.py",
            "description": "d", "variables": ["language"],
            "system": "Answer in $language. Example: {\"a\": 1}",
            "changelog": [{"version": "1.1", "date": "2026-10-20", "author": "T", "change": "c"},
                          {"version": "1.0", "date": "2026-10-19", "author": "T", "change": "first"}]}
    data.update(override)
    (folder / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_real_prompt_file_is_valid():
    p = load_prompt("comparison_summary")
    assert p.ref.startswith("prompt:comparison_summary@")
    assert "French" in p.render(language="French")


def test_render_keeps_json_braces(tmp_path):
    write(tmp_path, "demo")
    assert load_prompt("demo", tmp_path).render(language="French") == 'Answer in French. Example: {"a": 1}'


def test_version_must_be_logged(tmp_path):
    write(tmp_path, "demo", version="1.2")          # changed version, forgot the changelog
    with pytest.raises(ValidationError, match="first changelog entry"):
        load_prompt("demo", tmp_path)


def test_variables_must_be_declared(tmp_path):
    write(tmp_path, "demo", variables=[])
    with pytest.raises(ValidationError, match="declares"):
        load_prompt("demo", tmp_path)


def test_missing_value_is_refused(tmp_path):
    write(tmp_path, "demo")
    with pytest.raises(ValueError, match="needs values"):
        load_prompt("demo", tmp_path).render()
