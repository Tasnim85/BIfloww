"""Public entrypoint specified by contracts.pipeline."""
from contracts import AgentResult, RunContext
from bo2.contract_adapter import execute
from cleaning.agent import run as engine
from pathlib import Path
from contracts.quality import Playbook
from contracts.semantic import load_yaml


def dispatch(ctx):
    """Accept shared JSON/YAML playbooks without changing the local LLM workflow."""
    if ctx.params.get('playbook_mode')=='generate':
        return engine(ctx)
    explicit=ctx.params.get('playbook')
    directory=ctx.inputs.get('playbooks',ctx.params.get('playbook_dir',Path(__file__).parent/'playbooks'))
    candidates=[Path(explicit)] if explicit else sorted(p for p in Path(directory).glob('*') if p.suffix in {'.json','.yaml','.yml'}) if directory else []
    import pandas as pd
    import json
    from cleaning.shared_playbook import compatible, run as apply
    frames={p.stem:pd.read_parquet(p) for p in ctx.inputs['tables'].glob('*.parquet')}
    approved=[]; locations={}
    for path in candidates:
        if not path.is_file(): continue
        from bo2.artifact_io import details_path
        if path.name.endswith('.bo2.json'): continue
        data=json.loads(path.read_text(encoding='utf-8')) if path.suffix=='.json' else __import__('yaml').safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or 'source' not in data: continue
        book=Playbook.model_validate(data)
        if compatible(book,frames):
            approved.append(book);locations[book.ref]=path
    if approved:
        if len({b.name for b in approved})!=1 and not explicit:
            raise ValueError('Several playbook families need explicit selection')
        book=max(approved,key=lambda b:tuple(map(int,b.version.split('.'))))
        if not book.approved_by and not explicit:
            # The orchestrator can display the chosen draft for review.
            chosen=locations[book.ref]
            ctx=ctx.model_copy(update={'params':{**ctx.params,'playbook':str(chosen)}})
        return apply(ctx,book)
    if explicit and Path(explicit).is_file():
        import json
        p=Path(explicit)
        data=json.loads(p.read_text(encoding='utf-8')) if p.suffix=='.json' else __import__('yaml').safe_load(p.read_text(encoding='utf-8'))
        if isinstance(data,dict) and 'source' in data:
            # An incompatible shared book requests fresh rules, not legacy parsing.
            ctx=ctx.model_copy(update={'params':{**ctx.params,'playbook_mode':'generate'}})
    return engine(ctx)


def run(ctx: RunContext) -> AgentResult:
    return execute(ctx, dispatch)
