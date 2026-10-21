"""Private BO2 details are separate from the strict shared exchange files."""
import json
from pathlib import Path

FILES = {'pii_report.json', 'profile_report.json', 'coverage_profile.json',
         'anomaly_report.json', 'cleaning_report.json', 'warehouse_manifest.json',
         'receipts.json', 'lineage.json'}


def details_path(path):
    path = Path(path)
    return path.with_name(path.stem + '.bo2.json')


def read_artifact_text(path, encoding='utf-8', **kwargs):
    path = Path(path)
    text = path.read_text(encoding=encoding, **kwargs)
    if path.name not in FILES:
        return text
    data = json.loads(text)
    if not isinstance(data, dict) or 'contract_version' not in data:
        return text  # Historical results remain readable and are not rewritten.
    from contracts.registry import CONTRACT_OF
    from contracts.pipeline import STEPS
    ref = next(ref for ref in CONTRACT_OF if STEPS[ref.split('.')[0]].outputs[ref.split('.')[1]] == path.name)
    CONTRACT_OF[ref].model_validate(data)
    private = details_path(path)
    if private.is_file():
        import hashlib
        proof=private.with_suffix('.sha256')
        if not proof.is_file() or proof.read_text(encoding='ascii').strip()!=hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('Shared artifact changed independently of its BO2 details')
        return private.read_text(encoding=encoding)
    # An upstream agent is not required to provide BO2-specific metadata.
    if path.name == 'profile_report.json':
        data = {'tables': {t['table']: {'rows': t['rows'], 'duplicate_rows': t['duplicate_rows'],
                'columns': {c['name']: {k:c[k] for k in ('dtype','missing','distinct')} for c in t['columns']}} for t in data['tables']}}
    elif path.name == 'pii_report.json':
        actions = {'kept':'keep', 'pseudonymized':'hmac_sha256', 'generalized':'generalize_coordinate', 'dropped':'redact_text'}
        data = {**data, 'classification': [{**c, 'action': actions[c['action']]} for c in data['columns']]}
    elif path.name == 'cleaning_report.json':
        changes=[{'table':t,'rows_before':before,'rows_after':data['rows_after'].get(t,before),
            'removed_exact_duplicates':before-data['rows_after'].get(t,before)} for t,before in data['rows_before'].items()]
        changes += [{'table':r['table'],'column':r['column'],'action':r['rule_id']} for r in data['applied'] if r['column']]
        data = {**data, 'selection':'existing','playbook_version':'playbook:'+data['playbook'] if data['playbook'] else 'playbook:pending@0.0',
            'changes':changes,'needs_review': [] if data['playbook'] and not data['proposed_rules'] else [{'reason':'human_approval_required' if data['proposed_rules'] else 'critical_values_require_review'}]}
    elif path.name == 'receipts.json':
        data = data['receipts']
    return json.dumps(data)
