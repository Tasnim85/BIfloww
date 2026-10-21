"""Prompt registry: every LLM prompt of BIFlow lives in a YAML file in prompts/,
never inside the Python code. Owner of this loader: Tasnim. Each prompt file has its owner.

    prompts/<name>.yaml      one prompt = one file, versioned in Git

To change a prompt: edit its file, raise `version`, add a line at the TOP of
`changelog`. The code never changes. The journal records "prompt:<name>@<version>"
and the hash of the exact text sent, so any answer can be traced to its prompt.

Variables are written $name in the text (not {name}, so JSON examples with braces
stay safe) and must be declared in `variables`.
"""
from pathlib import Path
from string import Template

import yaml
from pydantic import Field, model_validator

from contracts.common import Contract

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptChange(Contract):
    version: str
    date: str                       # ISO date
    author: str
    change: str                     # what changed and why, one or two sentences


class Prompt(Contract):
    name: str
    version: str
    owner: str
    used_by: str                    # module that uses it, e.g. "comparisons/narrate.py"
    description: str
    variables: list[str] = Field(default_factory=list)
    system: str
    changelog: list[PromptChange]   # newest first

    @model_validator(mode="after")
    def _consistent(self):
        if not self.changelog or self.changelog[0].version != self.version:
            raise ValueError(f"prompt '{self.name}': the first changelog entry must be version "
                             f"{self.version}. Did you forget to log your change?")
        used = set(Template(self.system).get_identifiers())
        if used != set(self.variables):
            raise ValueError(f"prompt '{self.name}': text uses {sorted(used)} "
                             f"but declares {sorted(self.variables)}")
        return self

    @property
    def ref(self) -> str:
        return f"prompt:{self.name}@{self.version}"

    def render(self, **values) -> str:
        missing = set(self.variables) - set(values)
        if missing:
            raise ValueError(f"prompt '{self.name}' needs values for {sorted(missing)}")
        return Template(self.system).substitute(values)


def load_prompt(name: str, folder: Path = PROMPTS_DIR) -> Prompt:
    """Read the file at each call: an edited prompt is used without touching the code."""
    path = Path(folder) / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No prompt file {path}")
    prompt = Prompt.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if prompt.name != name:
        raise ValueError(f"{path.name} declares name '{prompt.name}'")
    return prompt


def all_prompts(folder: Path = PROMPTS_DIR) -> list[Prompt]:
    return [load_prompt(p.stem, folder) for p in sorted(Path(folder).glob("*.yaml"))]


if __name__ == "__main__":      # python -m contracts.prompts  -> list every prompt
    for p in all_prompts():
        print(f"{p.ref:<45} owner={p.owner:<8} used by {p.used_by}")
        print(f"   last change ({p.changelog[0].date}): {p.changelog[0].change}")
