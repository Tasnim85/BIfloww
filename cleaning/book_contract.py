"""Represent BO2 playbooks with the team's Playbook model, without extra fields."""
import json
from pathlib import Path
from contracts import save
from contracts.quality import Playbook, CleaningRule


def from_local(data):
    rules=[]
    if 'rules' in data:
        from bo2.contract_adapter import proposed_rules
        action={'trim':'normalize_text','numeric':'cast','datetime':'cast','fill_constant':'fill_value'}
        for i,r in enumerate(data['rules']):
            params={'case':'preserve'} if r['action']=='trim' else {'dtype':'float64' if r['action']=='numeric' else 'datetime64[ns]'} if r['action'] in {'numeric','datetime'} else {'value':r['value']}
            rules.append(CleaningRule(rule_id=f'R{i+1}',table=r['table'],column=r['column'],action=action[r['action']],params=params,description=f"{r['action']} sur {r['table']}.{r['column']}"))
        approval=data.get('approval',{})
        return Playbook(name=data['name'],version=data['version'],source='llm',approved_by=approval.get('reviewer'),approved_at=approval.get('approved_at'),rules=rules)
    for table in data['required_tables']:
        rules.append(CleaningRule(rule_id=f'text:{table}',table=table,action='normalize_text',
            params={'case':'preserve','empty_to_null':data['actions']['empty_strings_to_null'],
                'required_values':data.get('required_values',{}).get(table,[]),
                'nonnegative':data.get('critical_nonnegative_columns',{}).get(table,[])},
            description='Retirer les espaces et vérifier les champs critiques'))
        for column in data.get('numeric_columns',{}).get(table,[]):
            if column.endswith(('_id','_key','_lat','_lng')) or 'sequential' in column:
                continue
            rules.append(CleaningRule(rule_id=f'number:{table}.{column}',table=table,column=column,action='cast',params={'dtype':'float64'},description='Reconnaître les nombres sans inventer de valeur'))
        for column in data.get('date_columns',{}).get(table,[]):
            rules.append(CleaningRule(rule_id=f'date:{table}.{column}',table=table,column=column,action='cast',params={'dtype':'datetime64[ns]'},description='Reconnaître les dates sans inventer de valeur'))
        if data['actions']['remove_exact_duplicate_rows'] and table in data['deduplicate_tables']:
            rules.append(CleaningRule(rule_id=f'duplicates:{table}',table=table,action='drop_duplicates',description='Retirer les doublons strictement identiques'))
    # Do not fabricate an approval for the historical built-in configurations.
    return Playbook(name=data['name'],version=data['version'],source='manual',rules=rules)


def publish(path, data):
    from bo2.artifact_io import details_path
    path=Path(path);book=from_local(data)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_file():
        existing=json.loads(path.read_text(encoding='utf-8'))
        if 'source' in existing:
            current=Playbook.model_validate(existing)
            if current==book: return path
            if current.approved_by: raise ValueError('Conflicting published playbook version')
    details_path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    save(book,path)
    return path
