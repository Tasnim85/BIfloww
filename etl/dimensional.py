"""Reviewed dimensional ETL: actual fact/dimension tables, not labels on source copies."""
import json
from decimal import Decimal
import re
import unicodedata
import pandas as pd
from contracts.agent import AgentResult, AgentStatus
from contracts.warehouse import TransformationReceipt
from contracts.audit import AuditEvent, log_event
from .generic import inventory, relationships, quote, digest
from .dimensional_design import Plan, profile, propose, validate, reachable
from .models import WarehouseManifest

SK = "__bi_row_id"


def names_for(roles, metadata):
    result = {}; used = set()
    for role in roles:
        slug = unicodedata.normalize("NFKD",metadata[role.table]["source"]).encode("ascii","ignore").decode()
        slug = re.sub(r"[^a-zA-Z0-9_]+","_",slug).lower().strip("_")[:70] or role.table
        # Technical tables start with bi_: the names fact_/dim_ are kept for the shared views (etl/analytics.py).
        name = {"fact":"bi_fact_","dimension":"bi_dim_","reference":"bi_ref_","unresolved":"bi_other_"}[role.role] + slug
        if name in used or name=="dim_calendar":
            name += "_" + role.table
        used.add(name); result[role.table]=name
    return result


def build(connection,frames,metadata,profiles,plan):
    import duckdb  # deferred — fails fast if WDAC blocks the native extension
    roles = {r.table:r for r in plan.tables}
    names = names_for(plan.tables,metadata)
    candidates = relationships(frames,metadata)
    links = [l for l in candidates if l["id"] in plan.relationships]
    tables = {}; origins = {}; table_roles = {}; checks = []; receipts = []; column_sources = {}; stores = {}
    locations = {}; physical_columns = {}; measure_bindings = {}
    connection.execute("CREATE SCHEMA source")
    for table, frame in frames.items():
        if any(c.startswith("__bi_") for c in frame):
            raise ValueError("Reserved internal column prefix")
        connection.register("input_frame",frame)
        connection.execute(f'CREATE TABLE source.{quote(table)} AS SELECT * FROM input_frame')
        connection.unregister("input_frame")
        data=frame.copy(); data[SK]=range(1,len(data)+1)
        stores[table]=data
    def physical(name, frame, keys):
        connection.register("build_frame",frame)
        connection.execute(f"CREATE TABLE {name} AS SELECT * FROM build_frame")
        if keys:
            connection.execute(f"ALTER TABLE {name} ADD PRIMARY KEY ({','.join(map(quote,keys))})")
        connection.unregister("build_frame")
    def receipt(name,sources,before,after,grain="source_row",join_keys=None,filters=None):
        receipts.append(TransformationReceipt(output_table=name,source_tables=sources,rows_before=before,rows_after=after,
            grain=grain,join_keys=join_keys or [],filters=filters or []).model_dump())
    generated = {}; date_specs = {}; all_dates=[]
    for table,role in roles.items():
        if role.role!="fact":
            continue
        paths=reachable(table,links)
        specs=[(table,c,[]) for c in role.dates]
        for parent,path in paths.items():
            if roles[parent].role!="unresolved":
                specs.extend((parent,c,path) for c in profiles[parent]["valid_date_columns"][:1])
        date_specs[table]=specs
        for owner,column,path in specs:
            dates=pd.to_datetime(frames[owner][column],format="mixed",errors="raise",utc=True).dt.date
            all_dates.extend(d for d in dates if pd.notna(d))
        for column in role.dimensions:
            name=f"dim_{table}_{len(generated)+1}"
            frame=frames[table][[column]].drop_duplicates().reset_index(drop=True)
            frame[SK]=range(1,len(frame)+1)
            generated[name] = {"frame":frame,"owner":table,"column":column}
    if all_dates:
        dates=pd.Series(sorted(set(all_dates)))
        calendar=pd.DataFrame({"date":dates})
        typed=pd.to_datetime(calendar.date)
        calendar[SK]=typed.dt.strftime("%Y%m%d").astype('int64')
        calendar["year"]=typed.dt.year;calendar["month"]=typed.dt.month;calendar["day"]=typed.dt.day
        physical('main.dim_calendar',calendar,[SK]); locations['dim_calendar']='main.dim_calendar'
        table_roles['dim_calendar']='dimension'; origins['dim_calendar']="Calendrier"
        column_sources['dim_calendar']={c:list(dict.fromkeys(metadata[o]['source']+'.'+col for specs in date_specs.values() for o,col,path in specs)) for c in calendar}
        date_sources=list(dict.fromkeys(metadata[o]["source"] for specs in date_specs.values() for o,c,p in specs))
        receipt('dim_calendar',date_sources,sum(len(frames[o]) for o in {x[0] for specs in date_specs.values() for x in specs}),len(calendar),'calendar_day',filters=['distinct dates from approved fact date roles'])
    # Dimension/reference tables are materialized; snowflake really removes a repeated attribute from the base.
    for table,role in roles.items():
        if role.role=="fact":
            continue
        name=names[table]; data=stores[table].copy(); normalization=[]
        if plan.schema_type=="snowflake" and role.role=="dimension":
            for n,column in enumerate(profiles[table]["normalizable_columns"][:1]):
                ref=f"ref_{table}_attribute_{n+1}"
                values=data[[column]].drop_duplicates().reset_index(drop=True);values[SK]=range(1,len(values)+1)
                physical('main.'+ref,values,[SK])
                fk=f"__bi_attribute_{n+1}"
                merged=data[[column]].merge(values,on=column,how="left",sort=False)
                data[fk]=merged[SK].to_numpy();data=data.drop(columns=[column])
                normalization.append((column,ref,fk))
                table_roles[ref]='reference';origins[ref]=metadata[table]["source"]+" / "+column
                locations[ref]='main.'+ref
                column_sources[ref]={column:[f'{metadata[table]["source"]}.{column}'],SK:[f'{metadata[table]["source"]}.{column}']}
                receipt(ref,[metadata[table]["source"]],len(frames[table]),len(values),'distinct_attribute',filters=[f'distinct {column}'])
        base='main.'+quote(name+'_base' if normalization else name)
        physical(base,data,[SK])
        if normalization:
            projection=[]; joins=[]
            for col in stores[table]:
                match=next(((i,ref,fk) for i,(c,ref,fk) in enumerate(normalization) if c==col),None)
                projection.append(f'r{match[0]}.{quote(col)} AS {quote(col)}' if match else f'b.{quote(col)}')
            for i,(c,ref,fk) in enumerate(normalization):
                joins.append(f'LEFT JOIN main.{ref} r{i} ON b.{quote(fk)}=r{i}.{quote(SK)}')
            connection.execute(f'CREATE VIEW {quote(name)} AS SELECT {", ".join(projection)} FROM {base} b '+" ".join(joins))
        locations[name]=base.replace(chr(34),"")
        physical_columns[name]={c: "main."+ref+"."+c for c,ref,fk in normalization}
        table_roles[name]=role.role;origins[name]=metadata[table]['source']
        column_sources[name]={col:[f'{metadata[table]["source"]}.{col}'] for col in frames[table]}
        column_sources[name][SK]=[f'{metadata[table]["source"]}.{col}' for col in metadata[table]['primary_key']]
        receipt(name,[metadata[table]['source']],len(frames[table]),len(data),role.grain)
    for name, spec in generated.items():
        physical('main.'+quote(name),spec['frame'],[SK]);locations[name]='main.'+name
        table_roles[name]='dimension';origins[name]=metadata[spec['owner']]['source']+' / '+spec['column']
        column_sources[name]={col:[f'{metadata[spec["owner"]]["source"]}.{spec["column"]}'] for col in spec['frame']}
        receipt(name,[metadata[spec['owner']]['source']],len(frames[spec['owner']]),len(spec['frame']),'distinct_category',filters=['distinct '+spec['column']])
    for table,role in roles.items():
        if role.role!='fact':
            continue
        data=stores[table].copy();paths=reachable(table,links);fact_links=[];fact_sources=[metadata[table]['source']]
        def map_parent(owner,path):
            current=stores[table].copy();current['__bi_position']=range(len(current))
            for edge in path:
                parent=stores[edge['parent']]
                keys=edge['columns']
                # SQL semantics for null foreign keys: never match pandas null to a null parent.
                current=current.merge(parent,how='left',on=keys,suffixes=('_previous',''),sort=False,validate='many_to_one')
                # After each hop retain only the parent columns and source position.
                columns=['__bi_position']+[c for c in parent]
                current=current[columns]
            return current.sort_values('__bi_position').reset_index(drop=True)
        for parent,path in paths.items():
            if roles[parent].role!='dimension':
                continue
            mapped=map_parent(parent,path)
            fk='__bi_fk_'+parent
            data[fk]=pd.array(mapped[SK],dtype='Int64')
            fact_links.append({'column':fk,'dimension':names[parent],'target_key':SK,'source_path':[e['id'] for e in path]})
            fact_sources.extend(metadata[e['parent']]['source'] for e in path)
        for i,(owner,column,path) in enumerate(date_specs[table]):
            mapped=stores[table] if not path else map_parent(owner,path)
            dates=pd.to_datetime(mapped[column],format='mixed',errors='raise',utc=True)
            fk=f'__bi_date_{i+1}'
            data[fk]=pd.array(dates.dt.strftime('%Y%m%d'),dtype='Int64')
            fact_links.append({'column':fk,'dimension':'dim_calendar','target_key':SK,'source_path':[e['id'] for e in path],'date_source':f'{metadata[owner]["source"]}.{column}'})
            fact_sources.append(metadata[owner]['source'])
        for dim,spec in generated.items():
            if spec['owner']!=table:
                continue
            fk='__bi_fk_'+dim
            mapped=data[[spec['column']]].merge(spec['frame'],on=spec['column'],how='left',sort=False,validate='many_to_one')
            data[fk]=pd.array(mapped[SK],dtype='Int64')
            fact_links.append({'column':fk,'dimension':dim,'target_key':SK,'source_path':[],'category_source':spec['column']})
        bindings=[]
        for i,column in enumerate(role.measures):
            output_column=column
            if not pd.api.types.is_numeric_dtype(frames[table][column]):
                output_column=f"__bi_measure_{i+1}"
                data[output_column]=frames[table][column].map(lambda value:None if pd.isna(value) else Decimal(str(value)))
            bindings.append({"source_column":column,"warehouse_column":output_column,"aggregation":"catalog_required"})
        measure_bindings[names[table]]=bindings
        name=names[table]; target='main.'+quote(name)
        if plan.schema_type=='star':
            schema='mart_'+table
            connection.execute('CREATE SCHEMA '+schema)
            target=schema+'.'+quote(name)
            for link in fact_links:
                dim=link['dimension']
                copied=schema+'.'+quote(dim)
                if not connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema=? AND table_name=?",[schema,dim]).fetchall()[0][0]:
                    connection.execute(f'CREATE TABLE {copied} AS SELECT * FROM main.{quote(dim)}')
                link['physical_dimension']=schema+'.'+dim
        physical(target,data,[SK])
        if plan.schema_type=='star':
            connection.execute(f'CREATE VIEW {quote(name)} AS SELECT * FROM {target}')
        locations[name]=target.replace(chr(34),"");table_roles[name]='fact';origins[name]=metadata[table]['source']
        column_sources[name]={c:[f'{metadata[table]["source"]}.{c}'] for c in frames[table]}
        column_sources[name][SK]=[f'{metadata[table]["source"]}.{c}' for c in metadata[table]['primary_key']]
        for binding in bindings:
            column_sources[name][binding['warehouse_column']]=[metadata[table]['source']+'.'+binding['source_column']]
        for link in fact_links:
            col=link['column'];dim=link['dimension']
            dimtarget=link.get('physical_dimension','main.'+dim)
            bad=connection.execute(f'SELECT count(*) FROM {target} f LEFT JOIN {dimtarget} d ON f.{quote(col)}=d.{quote(SK)} WHERE f.{quote(col)} IS NOT NULL AND d.{quote(SK)} IS NULL').fetchall()[0][0]
            if bad:
                raise ValueError('Invalid dimensional key')
            keys=[key for edge in candidates if edge['id'] in link['source_path'] for key in edge['columns']]
            column_sources[name][col]=[f'{metadata[table]["source"]}.{c}' for c in keys if c in frames[table]]
            if link.get('date_source'):
                column_sources[name][col]=[link['date_source']]
            if link.get('category_source'):
                column_sources[name][col]=[metadata[table]['source']+'.'+link['category_source']]
            checks.append({'fact':name,'dimension':dim,**link,'invalid_keys':0})
        receipt(name,list(dict.fromkeys(fact_sources)),len(frames[table]),len(data),role.grain,
            join_keys=list(dict.fromkeys(c for edge in candidates if edge['id'] in {x for l in fact_links for x in l['source_path']} for c in edge['columns'])))
    # All original values are compared to their analytical tables, not merely their source copies.
    for table,frame in frames.items():
        name=names[table];cols=','.join(map(quote,frame.columns))
        source='source.'+quote(table)
        original='SELECT '+cols+' FROM '+source
        actual='SELECT '+cols+' FROM '+quote(name)
        for left,right in [(original,actual),(actual,original)]:
            if connection.execute('SELECT count(*) FROM ('+left+' EXCEPT ALL '+right+')').fetchall()[0][0]:
                raise ValueError('Dimensional construction changed original rows or values')
        if connection.execute('SELECT count(*) FROM '+quote(name)).fetchall()[0][0]!=len(frame):
            raise ValueError('Dimensional construction multiplied rows')
    physical_tables={}
    def describe(schema,name,keys):
        full=quote(schema)+'.'+quote(name)
        return {'rows':connection.execute('SELECT count(*) FROM '+full).fetchall()[0][0],'grain':'source_row','primary_key':keys,
            'columns':[{'name':r[0],'type':r[1]} for r in connection.execute('DESCRIBE '+full).fetchall()], 'kind':'table'}
    for schema,name,kind in connection.execute("SELECT table_schema,table_name,table_type FROM information_schema.tables WHERE table_schema<>'source'").fetchall():
        if kind=='BASE TABLE':
            physical_tables[schema+'.'+name]=describe(schema,name,[SK] if SK in [r[0] for r in connection.execute('DESCRIBE '+quote(schema)+'.'+quote(name)).fetchall()] else [])
    for name,role in table_roles.items():
        info=describe('main',name,[SK]);info['kind']='view' if connection.execute("SELECT table_type FROM information_schema.tables WHERE table_schema='main' AND table_name=?",[name]).fetchall()[0][0]=='VIEW' else 'table'
        info['physical_sources']={c['name']:[physical_columns.get(name,{}).get(c['name'],locations[name]+'.'+c['name'])] for c in info['columns']}
        info['grain']=next(r['grain'] for r in receipts if r['output_table']==name)
        tables[name]=info
    from .analytics import build_views
    views,view_receipts=build_views(connection,frames,metadata,roles,names,links,date_specs,reachable)
    return {'analytic_views':views,'analytic_receipts':view_receipts,'tables':tables,'physical_tables':physical_tables,'source_tables':origins,'table_roles':table_roles,
        'source_storage_tables':{'source.'+t:describe('source',t,[]) for t in frames},
        'measure_bindings':measure_bindings,'dimensional_links':checks,'column_sources':column_sources,'receipts':receipts,'source_row_counts':{metadata[t]['source']:len(f) for t,f in frames.items()}}


def run(ctx):
    temporary=ctx.output_dir/'warehouse.building.duckdb';connection=None;owned=False;published=[];success=False
    try:
        ctx.output_dir.mkdir(parents=True,exist_ok=True)
        if any((ctx.output_dir/n).exists() for n in ['warehouse.duckdb','warehouse_manifest.json','receipts.json']):
            raise ValueError('Completed warehouse exists')
        frames,metadata,hashes=inventory(ctx);profiles=profile(frames,metadata);candidates=relationships(frames,metadata)
        proposal=ctx.output_dir/'warehouse_proposal.json'
        if proposal.exists():
            envelope=json.loads(proposal.read_text(encoding='utf-8'))
            if envelope.get('version')!=2 or envelope['source_fingerprints']!=hashes or envelope['tables']!=metadata or envelope['candidates']!=candidates or envelope['profiles']!=profiles or envelope.get('cleaning_source')!=str(ctx.inputs['tables'].parent.resolve()):
                raise ValueError('Proposal is obsolete or sources changed')
            plan=Plan.model_validate(envelope['design'])
        else:
            if ctx.params.get('etl_approval'):
                raise ValueError('No proposal to approve')
            plan=propose(profiles,candidates);validate(plan,profiles,candidates)
            envelope={'version':2,'cleaning_source':str(ctx.inputs['tables'].parent.resolve()),'source_fingerprints':hashes,
                'tables':metadata,'profiles':profiles,'candidates':candidates,'design':plan.model_dump()}
            proposal.write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8')
        validate(plan,profiles,candidates)
        if not ctx.params.get('etl_approval'):
            return AgentResult(run_id=ctx.run_id,agent='etl',status=AgentStatus.NEEDS_REVIEW,outputs={'proposal':proposal},message='Review fact/dimension roles and Llama3 schema recommendation')
        if ctx.params['etl_approval']!=digest(proposal):
            raise ValueError('Approval does not match proposal')
        if temporary.exists():
            raise ValueError('Unfinished build exists')
        connection=duckdb.connect(str(temporary));owned=True
        built=build(connection,frames,metadata,profiles,plan)
        connection.close();connection=None
        if inventory(ctx)[2]!=hashes:
            raise ValueError('Sources changed during preparation')
        warehouse=ctx.output_dir/'warehouse.duckdb'
        receipts=built.pop('receipts')
        manifest=WarehouseManifest(warehouse=str(warehouse),reconciliation=None,revenue_catalog_status='owned_by_Rabeb_not_defined_here',
            schema_type=plan.schema_type,schema_selection='llm',schema_recommendation=str(proposal),cleaning_source=str(ctx.inputs['tables'].parent.resolve()),
            source_fingerprints=hashes,approval_digest=ctx.params['etl_approval'],modeling_version=2,
            schema_rationale=plan.rationale,quality_checks={'all_rows_preserved':True,'all_values_preserved':True,'dimensional_keys_valid':True},**built)
        outputs={'warehouse':warehouse,'manifest':ctx.output_dir/'warehouse_manifest.json','receipts':ctx.output_dir/'receipts.json'}
        for path,content in [(outputs['manifest'],manifest.model_dump_json(indent=2)),(outputs['receipts'],json.dumps(receipts,indent=2))]:
            staging=path.with_suffix('.building.json')
            try:
                staging.write_text(content,encoding='utf-8');staging.rename(path);published.append(path)
            finally:
                staging.unlink(missing_ok=True)
        temporary.rename(warehouse);published.append(warehouse)
        log_event(AuditEvent(run_id=ctx.run_id,agent='etl',step='build_dimensional_warehouse',decision=plan.schema_type,
            rule_version='etl-dimensional@2.0',evidence={'roles':built['table_roles'],'approved_proposal_sha256':ctx.params['etl_approval']}),ctx.journal)
        success=True
        return AgentResult(run_id=ctx.run_id,agent='etl',status=AgentStatus.SUCCESS,outputs=outputs,message='Built validated dimensional layout '+plan.schema_type)
    except Exception as exc:
        import logging; logging.getLogger(__name__).exception("ETL dimensional failed")
        return AgentResult(run_id=ctx.run_id,agent='etl',status=AgentStatus.FAILED,message='DIMENSIONAL_ETL_'+type(exc).__name__+f': {exc}')
    finally:
        if connection is not None:
            connection.close()
        if owned:
            temporary.unlink(missing_ok=True)
        if not success:
            for path in published:
                path.unlink(missing_ok=True)
