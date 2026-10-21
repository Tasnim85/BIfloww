"""Publish the team contracts; retain UI metadata only in explicit private files."""
import json
from pathlib import Path

import pandas as pd
from contracts import AgentResult, AgentStatus, save
from contracts.common import SemanticType
from contracts.privacy import PiiReport, PiiColumn, PiiKind, PiiAction
from contracts.quality import (ProfileReport, TableProfile, ColumnProfile, CoverageProfile,
    TableCoverage, DayCoverage, AnomalyReport, CleaningReport, RuleApplication, CleaningRule)
from contracts.warehouse import (WarehouseManifest, WarehouseTable, TransformationReceipts,
    TransformationReceipt, LineageGraph, LineageNode, LineageEdge)
from bo2.artifact_io import details_path, read_artifact_text


def raw(path):
    return json.loads(read_artifact_text(path))


def publish(path, artifact):
    """Validate first; write private metadata before publishing the shared file."""
    path = Path(path)
    value = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(value, dict) and 'contract_version' in value:
        return path
    details_path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary = path.with_name(path.name + '.publishing')
    save(artifact, temporary)
    import hashlib
    details_path(path).with_suffix('.sha256').write_text(hashlib.sha256(temporary.read_bytes()).hexdigest(),encoding='ascii')
    temporary.replace(path)
    return path


def pii(ctx, result):
    path = result.outputs.get('report')
    if not path or not path.is_file():
        return
    data = raw(path)
    actions = {'keep':PiiAction.KEPT, 'hmac_sha256':PiiAction.PSEUDONYMIZED,
        'redact_text':PiiAction.GENERALIZED, 'redact_detected_pii':PiiAction.GENERALIZED,
        'generalize_coordinate':PiiAction.GENERALIZED, 'generalize_zip':PiiAction.GENERALIZED}
    kinds = {'PERSONAL_ID':'PERSON_ID', 'POSTAL_CODE':'ZIP_CODE', 'FREE_TEXT':'OTHER', 'COORDINATE':'OTHER'}
    columns=[]
    for c in data.get('classification', data.get('decisions', [])):
        kind=kinds.get(c.get('semantic_type'), c.get('semantic_type'))
        columns.append(PiiColumn(table=c['table'],column=c['column'],
            pii_kind=kind if kind in PiiKind._value2member_map_ else PiiKind.OTHER,
            action=actions[c['action']], method=c['action'],
            rows_affected=c['non_null_rows'] if c['action']!='keep' else 0))
    publish(path,PiiReport(policy_version=data['policy_version'],columns=columns,
        tables={n:p.name for n in data['tables'] if (p:=ctx.output_dir/'tables'/f'{n}.parquet').is_file()}))


def profiling(ctx, result):
    path=result.outputs.get('profile')
    if path and path.is_file():
        data=raw(path); semantic={}
        if (p:=ctx.inputs.get('column_types')) and p.is_file():
            from contracts.intake import ColumnTypesReport
            semantic={(c.table,c.column):c.semantic_type for c in ColumnTypesReport.model_validate_json(p.read_text(encoding='utf-8')).columns}
        tables=[]
        for name,table in data['tables'].items():
            columns=[ColumnProfile(name=name_col, dtype=c['dtype'], semantic_type=semantic.get((name,name_col)),
                missing=c['missing'],missing_pct=c['missing']/table['rows'] if table['rows'] else 0,
                distinct=c['distinct']) for name_col,c in table['columns'].items()]
            tables.append(TableProfile(table=name,rows=table['rows'],duplicate_rows=table['duplicate_rows'],columns=columns))
        publish(path,ProfileReport(tables=tables))
    path=result.outputs.get('coverage')
    if path and path.is_file():
        data=raw(path); tables=[]
        if data['period_start'] and data['period_end']:
            frame=pd.read_parquet(ctx.inputs['tables']/f"{data['source_table']}.parquet")
            dates=pd.to_datetime(frame[data['date_column']],format='mixed',errors='coerce',utc=True).dt.strftime('%Y-%m-%d')
            days=[]
            for day in pd.date_range(data['period_start'],data['period_end'],freq='D'):
                day=day.strftime('%Y-%m-%d'); subset=frame.loc[dates==day]
                statuses=subset[data['status_column']].astype('string').str.strip().replace('',pd.NA).fillna('__missing__')
                by_status={str(k):int(v) for k,v in statuses.value_counts().items()}
                days.append(DayCoverage(date=day,rows=len(subset),by_status=by_status,
                    completeness={c:float(subset[c].notna().mean()) if len(subset) else 0.0 for c in frame}))
            tables=[TableCoverage(table=data['source_table'],date_column=data['date_column'],status_column=data['status_column'],
                first_day=data['period_start'],last_day=data['period_end'],days=days)]
        publish(path,CoverageProfile(tables=tables))
    path=result.outputs.get('anomalies')
    if path and path.is_file():
        data=raw(path)
        publish(path,AnomalyReport(table=data['table'],row_key='source_row',model='IsolationForest',model_version='iforest@2.0',
            params={'n_estimators':data['n_estimators'],'contamination':data['contamination'],'random_state':data['seed'],
                'preprocessing':'median','score_definition':data['score_definition'],'shap':data['shap']},features=data['features'],
            n_rows=data['rows'],n_anomalies=data['flagged']))


def proposed_rules(path):
    if not path or not path.is_file():
        return []
    data=json.loads(path.read_text(encoding='utf-8'))
    return [CleaningRule(rule_id=f"R{i+1}",table=r['table'],column=r['column'],
        action={'trim':'normalize_text','numeric':'cast','datetime':'cast','fill_constant':'fill_value'}[r['action']],
        params={'case':'preserve'} if r['action']=='trim' else {'dtype':'float64' if r['action']=='numeric' else 'datetime64[ns]'} if r['action'] in {'numeric','datetime'} else {'value':r['value']},
        description=f"{r['action']} sur {r['table']}.{r['column']}") for i,r in enumerate(data['rules'])]


def cleaning(ctx,result):
    path=result.outputs.get('report')
    if not path or not path.is_file():
        return
    if 'contract_version' in json.loads(path.read_text(encoding='utf-8')):
        return
    data=raw(path); before={p.stem:len(pd.read_parquet(p)) for p in ctx.inputs['tables'].glob('*.parquet')}
    after={p.stem:len(pd.read_parquet(p)) for p in (ctx.output_dir/'tables').glob('*.parquet')}
    applied=[]
    if result.status==AgentStatus.SUCCESS:
        mapping_path=ctx.output_dir/'row_mapping.json'
        mapping=json.loads(mapping_path.read_text(encoding='utf-8')) if mapping_path.is_file() else {}
        for name in before:
            old=pd.read_parquet(ctx.inputs['tables']/f'{name}.parquet')
            new=pd.read_parquet(ctx.output_dir/'tables'/f'{name}.parquet')
            ids=mapping.get(name,list(range(len(new))))
            for col in new:
                left=old.iloc[ids][col].reset_index(drop=True); right=new[col].reset_index(drop=True)
                same=(left.astype('string')==right.astype('string')).fillna(False) | (left.isna() & right.isna())
                changed=int((~same).sum())
                if changed:
                    applied.append(RuleApplication(rule_id=f'change:{name}.{col}',table=name,column=col,rows_affected=changed))
            if before[name]!=after[name]:
                applied.append(RuleApplication(rule_id=f'deduplicate:{name}',table=name,rows_affected=before[name]-after[name]))
    publish(path,CleaningReport(playbook=data['playbook_version'].removeprefix('playbook:') if result.status==AgentStatus.SUCCESS else None,
        applied=applied,proposed_rules=proposed_rules(result.outputs.get('proposal')) if result.status==AgentStatus.NEEDS_REVIEW else [],
        rows_before=before,rows_after=after,tables={name:f'{name}.parquet' for name in after}))
    if result.status==AgentStatus.SUCCESS and (book_path:=result.outputs.get('playbook')):
        from cleaning.book_contract import publish as publish_book
        book=json.loads(book_path.read_text(encoding='utf-8'))
        directory=Path(ctx.params.get('playbook_dir',Path(__file__).resolve().parents[1]/'cleaning/playbooks'))
        registered=publish_book(directory/book_path.name,book)
        result.outputs['playbook']=registered


def etl(ctx,result):
    if result.status!=AgentStatus.SUCCESS:
        return
    path=result.outputs['manifest']; data=raw(path)
    import duckdb
    conn=duckdb.connect(str(result.outputs['warehouse']),read_only=True)
    tables=[]
    try:
        for name,t in data['tables'].items():
            role=data.get('table_roles',{}).get(name)
            if role in {'unresolved','data'}:
                # Preserve these sources in DuckDB/private metadata without inventing
                # a business role the shared manifest cannot express.
                continue
            kind='fact' if role in {'fact','activity'} or name.startswith('fact_') else 'dimension'
            columns=[c['name'] for c in t['columns']]
            temporal=[c['name'] for c in t['columns'] if any(token in c['type'].upper() for token in ('DATE','TIME'))]
            # The reviewed plan may designate a source date stored as text.
            proposal=ctx.output_dir/'warehouse_proposal.json'
            if not temporal and proposal.is_file():
                design=json.loads(proposal.read_text(encoding='utf-8')).get('design',{})
                origin=data.get('source_tables',{}).get(name)
                for advice in design.get('tables',[]):
                    source_id=advice.get('table')
                    metadata=json.loads(proposal.read_text(encoding='utf-8')).get('tables',{}).get(source_id,{})
                    if metadata.get('source')==origin:
                        temporal=[c for c in advice.get('dates',[]) if c in columns]
            date_column=temporal[0] if kind=='fact' and temporal else None
            minimum=maximum=None
            if date_column:
                quote=lambda s:'"'+s.replace('"','""')+'"'
                minimum,maximum=conn.execute(f'SELECT min(try_cast({quote(date_column)} AS DATE)),max(try_cast({quote(date_column)} AS DATE)) FROM {quote(name)}').fetchone()
            tables.append(WarehouseTable(name=name,kind=kind,grain=t['grain'],primary_key=t['primary_key'],row_count=t['rows'],columns=columns,
                date_column=date_column,date_min=str(minimum) if minimum else None,date_max=str(maximum) if maximum else None))
    finally:
        conn.close()
    receipt_data=raw(result.outputs['receipts'])
    source_columns={p.stem:set(pd.read_parquet(p).columns) for p in ctx.inputs['tables'].glob('*.parquet')}
    receipts=[]
    for receipt in receipt_data:
        if receipt['output_table'] not in {t.name for t in tables} and receipt['output_table'] in data['tables']:
            continue
        sources=data.get('column_sources',{}).get(receipt['output_table'],{})
        if not sources and receipt['output_table'] in data['tables']:
            sources={c['name']:[s+'.'+c['name'] for s in receipt['source_tables'] if c['name'] in source_columns.get(s,set())]
                for c in data['tables'][receipt['output_table']]['columns']}
            sources={c:refs for c,refs in sources.items() if refs}
        receipts.append(TransformationReceipt(**{**receipt,'column_sources':{k:' | '.join(v) for k,v in sources.items()} if sources else receipt.get('column_sources',{})}))
    manifest=WarehouseManifest(database_file=result.outputs['warehouse'].name,tables=tables)
    wrapped=TransformationReceipts(receipts=receipts)
    publish(path,manifest);publish(result.outputs['receipts'],wrapped)


def lineage(ctx,result):
    path=result.outputs.pop('lineage',None) or result.outputs.get('graph')
    if not path or not path.is_file():
        return
    if 'contract_version' in json.loads(path.read_text(encoding='utf-8')):
        result.outputs['graph']=path
        return
    data=raw(path)
    def kind(node):
        return 'raw_column' if node['kind']=='raw' and '.' in node['id'] else 'kpi' if node['kind']=='kpi' else 'transformation' if '.' in node['id'] or node['kind']=='transformation' else 'table'
    publish(path,LineageGraph(nodes=[LineageNode(id=n['id'],kind=kind(n),label=n['id']) for n in data['nodes']],
        edges=[LineageEdge(source=e['source'],target=e['target'],relation=e['operation']) for e in data['edges']]))
    result.outputs['graph']=path


EXPORTERS={'pii':pii,'profiling':profiling,'cleaning':cleaning,'etl':etl,'lineage':lineage}


def shared_lineage(ctx):
    """Build lineage from shared receipts alone, without a BO2 metadata sidecar."""
    from contracts.registry import read_output
    manifest=read_output(ctx.inputs['manifest'],'etl.manifest')
    receipts=read_output(ctx.inputs['receipts'],'etl.receipts')
    names={t.name:t for t in manifest.tables};nodes={};edges=[]
    written=[r.output_table for r in receipts.receipts if r.output_table in names]
    if len(names)!=len(manifest.tables) or set(written)!=set(names) or len(written)!=len(set(written)):
        raise ValueError('Missing or duplicate table/receipt')
    if any(r.rows_after!=names[r.output_table].row_count for r in receipts.receipts if r.output_table in names):
        raise ValueError('Receipt and manifest row counts disagree')
    for receipt in receipts.receipts:
        if receipt.output_table not in names: continue
        table=names[receipt.output_table]
        target='warehouse:'+table.name
        nodes[target]=LineageNode(id=target,kind='table',label=table.name)
        for column,source in receipt.column_sources.items():
            if column not in table.columns: raise ValueError('Unknown receipt column')
            output=f'warehouse:{table.name}.{column}'
            nodes[output]=LineageNode(id=output,kind='transformation',label=f'{table.name}.{column}')
            # A source expression may describe more than one dependency.
            import re
            for ref in re.findall(r'\b([A-Za-z_][\w]*\.[A-Za-z_][\w]*)\b',source):
                node='raw:'+ref;nodes[node]=LineageNode(id=node,kind='raw_column',label=ref)
                edges.append(LineageEdge(source=node,target=output,relation='receipt_column_source'))
            edges.append(LineageEdge(source=output,target=target,relation='column_of'))
        if not receipt.column_sources:
            for source in receipt.source_tables:
                node='clean:'+source;nodes[node]=LineageNode(id=node,kind='table',label=source)
                edges.append(LineageEdge(source=node,target=target,relation='receipt_source_table'))
    bindings=catalog_bindings(ctx,names)
    for metric,binding in bindings.items():
        target='kpi:'+metric;nodes[target]=LineageNode(id=target,kind='kpi',label=metric)
        for ref in binding['sources']:
            node=f"warehouse:{ref['table']}.{ref['column']}"
            nodes.setdefault(node,LineageNode(id=node,kind='transformation',label=node))
            edges.append(LineageEdge(source=node,target=target,relation='catalog_binding'))
    graph=LineageGraph(nodes=list(nodes.values()),edges=list({(e.source,e.target,e.relation):e for e in edges}.values()))
    path=ctx.output('graph')
    if path.exists() and path.read_text(encoding='utf-8')!=graph.model_dump_json(indent=2):
        raise ValueError('Different lineage already exists')
    save(graph,path)
    outputs={'graph':path}
    if ctx.params.get('backend','neo4j')=='neo4j':
        from etl.neo4j_store import import_graph
        import hashlib
        scope=ctx.run_id+'__'+hashlib.sha256(graph.model_dump_json().encode()).hexdigest()[:16]
        try:
            report=import_graph(graph,scope)
        except Exception:
            return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.FAILED,outputs=outputs,message='Neo4j import unavailable; local graph retained')
        out=ctx.output_dir/'neo4j_import.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8');outputs['neo4j_import']=out
    return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.SUCCESS,outputs=outputs)


def catalog_bindings(ctx,tables):
    if not (path:=ctx.inputs.get('catalog')):
        return ctx.params.get('metric_sources',{})
    from contracts.semantic import KpiCatalog,load_yaml
    import re
    catalog=load_yaml(KpiCatalog,path);bindings={}
    for kpi in catalog.kpis:
        if kpi.table not in tables:
            raise ValueError(f'Catalogue KPI incompatible: {kpi.table}')
        table=tables[kpi.table]
        if kpi.date_column not in table.columns or kpi.grain!=table.grain:
            raise ValueError('KPI grain/date does not match the warehouse')
        expression=' '.join([kpi.expression,*kpi.filters])
        cols=[c for c in table.columns if re.search(r'(?<!\w)'+re.escape(c)+r'(?!\w)',expression)]
        if not cols: raise ValueError('KPI expression has no verified column dependency')
        bindings[kpi.ref]={'sources':[{'table':kpi.table,'column':c} for c in dict.fromkeys([*cols,kpi.date_column])]}
    return bindings


def execute(ctx,engine):
    """The adapter is the public entrypoint used by both the DAG and Streamlit."""
    try:
        from contracts.registry import read_output
        refs={'column_types':'column_types.report','profile':'profiling.profile','similarity':'similarity.report',
              'manifest':'etl.manifest','receipts':'etl.receipts','cleaning_report':'cleaning.report'}
        for key,ref in refs.items():
            if p:=ctx.inputs.get(key):
                if not p.is_file(): raise ValueError(f'Missing input: {key}')
                data=json.loads(p.read_text(encoding='utf-8'))
                if isinstance(data,dict) and 'contract_version' in data:
                    read_output(p,ref)
        # pipeline.py supplies only cleaning.tables to ETL.
        if ctx.agent=='etl' and 'cleaning_report' not in ctx.inputs:
            report=ctx.inputs['tables'].parent/'cleaning_report.json'
            read_output(report,'cleaning.report')
            ctx=ctx.model_copy(update={'inputs':{**ctx.inputs,'cleaning_report':report}})
        if ctx.agent=='cleaning' and 'playbooks' in ctx.inputs:
            ctx=ctx.model_copy(update={'params':{'playbook_dir':ctx.inputs['playbooks'],**ctx.params}})
        if ctx.agent=='lineage' and not details_path(ctx.inputs['manifest']).is_file() and 'contract_version' in json.loads(ctx.inputs['manifest'].read_text(encoding='utf-8')):
            result=shared_lineage(ctx)
        else:
            if ctx.agent=='lineage' and ctx.inputs.get('catalog'):
                from contracts.registry import read_output
                manifest=read_output(ctx.inputs['manifest'],'etl.manifest')
                bindings=catalog_bindings(ctx,{t.name:t for t in manifest.tables})
                ctx=ctx.model_copy(update={'params':{**ctx.params,'metric_sources':bindings}})
            result=engine(ctx)
        EXPORTERS[ctx.agent](ctx,result)
        ctx.log('contract_publication',result.status.value,outputs=[str(p) for p in result.outputs.values()],rule_version='contracts:bo2@1.1')
        return result
    except Exception as exc:
        try:
            ctx.log('contract_publication','FAILED',evidence={'error_type':type(exc).__name__},rule_version='contracts:bo2@1.1')
        except Exception:
            pass  # Audit failure must still return FAILED, never a false SUCCESS.
        return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.FAILED,message=f'CONTRACT_VALIDATION: {type(exc).__name__}: {exc}')
