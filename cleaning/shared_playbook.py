"""Execute approved shared playbooks with explicit actions, never eval/query."""
import json
import re
import tempfile
from pathlib import Path
import pandas as pd
from contracts import AgentResult, AgentStatus, save
from contracts.quality import Playbook, CleaningReport, RuleApplication
from cleaning.identifiers import is_financial, is_identifier


def compatible(book, frames):
    return all(r.table in frames and (r.column is None or r.column in frames[r.table]) for r in book.rules)


def run(ctx, book):
    frames={p.stem:pd.read_parquet(p) for p in ctx.inputs['tables'].glob('*.parquet')}
    before={t:len(f) for t,f in frames.items()}
    if not compatible(book,frames):
        raise ValueError('Playbook incompatible with the protected sources')
    if not book.approved_by or not book.approved_at:
        report=CleaningReport(playbook=None,proposed_rules=book.rules,rows_before=before,rows_after={},tables={})
        outputs={'report':save(report,ctx.output('report'))}
        if ctx.params.get('playbook'): outputs['playbook']=Path(ctx.params['playbook'])
        return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.NEEDS_REVIEW,
            outputs=outputs,message='Playbook approval required')
    if (ctx.output_dir/'tables').exists():
        raise ValueError('Completed cleaning cannot be overwritten')
    applied=[]
    from bo2.artifact_io import read_artifact_text
    pii=ctx.inputs['tables'].parent/'pii_report.json'
    protected={}
    if pii.is_file():
        data=json.loads(read_artifact_text(pii))
        protected={(c['table'],c['column']):c for c in data.get('classification',[])}
    if 'column_types' in ctx.inputs:
        from contracts.intake import ColumnTypesReport
        for c in ColumnTypesReport.model_validate_json(ctx.inputs['column_types'].read_text(encoding='utf-8')).columns:
            if c.semantic_type.value=='ID':
                protected[(c.table,c.column)]={**protected.get((c.table,c.column),{}),'semantic_type':'INTERNAL_KEY','action':'keep'}
    for rule in book.rules:
        frame=frames[rule.table]; col=rule.column; action=rule.action.value
        decision=protected.get((rule.table,col),{})
        if decision and (decision.get('action')!='keep' or decision.get('semantic_type') in {'PERSONAL_ID','INTERNAL_KEY','BUSINESS_KEY','POSTAL_CODE'}):
            raise ValueError('Playbook would modify a protected column or identifier')
        sensitive=bool(col and (is_identifier(col) or is_financial(col) or re.search('date|timestamp',col,re.I)))
        if sensitive and action in {'fill_median','fill_value','to_abs','clip'}:
            raise ValueError('Cannot fabricate or silently correct critical data')
        old=frame.copy()
        if action=='drop_duplicates':
            subset=rule.params.get('subset')
            if subset and not set(subset).issubset(frame):
                raise ValueError('Unknown duplicate key')
            frame=frame.drop_duplicates(subset=subset).copy()
        elif action=='drop_row':
            # Arbitrary expression execution is deliberately unsupported.
            raise ValueError('drop_row needs an explicit reviewed implementation; expressions are not executed')
        elif action=='normalize_text' and not col:
            for column in frame.select_dtypes(include=['object','string']):
                info=protected.get((rule.table,column),{})
                if info and (info.get('action')!='keep' or info.get('semantic_type') in {'PERSONAL_ID','INTERNAL_KEY','BUSINESS_KEY','POSTAL_CODE'}):
                    continue
                frame[column]=frame[column].astype('string').str.strip()
                if rule.params.get('empty_to_null'): frame[column]=frame[column].replace('',pd.NA)
        elif not col:
            raise ValueError('This rule needs a column')
        elif action=='normalize_text':
            series=frame[col]
            if pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
                series=series.astype('string').str.strip()
                case=rule.params.get('case','preserve')
                if case=='lower': series=series.str.lower()
                elif case=='title': series=series.str.title()
                elif case!='preserve': raise ValueError('Unknown text normalization')
                frame[col]=series
        elif action=='cast':
            dtype=rule.params['dtype']
            if dtype.startswith('datetime'):
                converted=pd.to_datetime(frame[col],format='mixed',errors='coerce')
            elif dtype in {'float64','int64','Int64','Float64'}:
                converted=pd.to_numeric(frame[col],errors='coerce').astype(dtype)
            elif dtype in {'string','str'}:
                converted=frame[col].astype('string')
            else:
                raise ValueError('Unsupported cast')
            if (frame[col].notna() & converted.isna()).any():
                raise ValueError('Conversion would lose values')
            frame[col]=converted
        elif action=='fill_value':
            if rule.params.get('value') is None:
                raise ValueError('Missing fill value')
            frame[col]=frame[col].fillna(rule.params['value'])
        elif action=='fill_median':
            values=pd.to_numeric(frame[col],errors='raise');median=values.median()
            if pd.isna(median): raise ValueError('No median available')
            frame[col]=values.fillna(median)
        elif action=='to_abs':
            frame[col]=pd.to_numeric(frame[col],errors='raise').abs()
        elif action=='clip':
            frame[col]=pd.to_numeric(frame[col],errors='raise').clip(lower=rule.params.get('lower'),upper=rule.params.get('upper'))
        else:
            raise ValueError('Unsupported cleaning action')
        if len(old)!=len(frame):
            affected=len(old)-len(frame)
        elif col:
            same=old[col].astype('string').eq(frame[col].astype('string')).fillna(False) | (old[col].isna() & frame[col].isna())
            affected=int((~same).sum())
        else:
            same=(old.astype('string').eq(frame.astype('string')).fillna(False) | (old.isna() & frame.isna())).all(axis=1)
            affected=int((~same).sum())
        frames[rule.table]=frame
        applied.append(RuleApplication(rule_id=rule.rule_id,table=rule.table,column=col,rows_affected=affected))
        ctx.log(rule.rule_id,'applied',rule_version='playbook:'+book.ref,evidence={'rows_affected':affected})
    for rule in book.rules:
        frame=frames[rule.table]
        for col in rule.params.get('required_values',[]):
            if col not in frame or frame[col].isna().any():
                ctx.log(rule.rule_id,'needs_review',evidence={'reason':'missing_required_values','table':rule.table,'column':col})
                report=CleaningReport(playbook=None,rows_before=before,rows_after={},tables={})
                return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.NEEDS_REVIEW,outputs={'report':save(report,ctx.output('report'))},message='Critical values require review')
        for col in rule.params.get('nonnegative',[]):
            values=pd.to_numeric(frame[col],errors='coerce')
            if values.isna().any() or values.lt(0).any():
                ctx.log(rule.rule_id,'needs_review',evidence={'reason':'invalid_financial_values','table':rule.table,'column':col})
                report=CleaningReport(playbook=None,rows_before=before,rows_after={},tables={})
                return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.NEEDS_REVIEW,outputs={'report':save(report,ctx.output('report'))},message='Critical values require review')
    ctx.output_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ctx.output_dir,prefix='.shared-cleaning-') as tmp:
        staging=Path(tmp)/'tables';staging.mkdir()
        for name,frame in frames.items(): frame.to_parquet(staging/f'{name}.parquet',index=False)
        staging.rename(ctx.output_dir/'tables')
    (ctx.output_dir/'row_mapping.json').write_text(json.dumps({t:[int(i) for i in f.index] for t,f in frames.items()}),encoding='utf-8')
    report=CleaningReport(playbook=book.ref,applied=applied,rows_before=before,
        rows_after={t:len(f) for t,f in frames.items()},tables={t:f'{t}.parquet' for t in frames})
    return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.SUCCESS,
        outputs={'report':save(report,ctx.output('report')),'tables':ctx.output('tables')})
