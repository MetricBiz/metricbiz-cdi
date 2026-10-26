"""Run in EPO TIP. Focused bibliographic export with query checkpoints.
Uses the supplied COMPANY inventory, not all RO applicants.
"""
from pathlib import Path
from datetime import datetime, timezone
import csv, hashlib, json, shutil
import pandas as pd
from sqlalchemy import func
from epo.tipdata.patstat import PatstatClient
from epo.tipdata.patstat.database import models as M
from IPython.display import display, FileLink

INPUT = Path.home() / 'solicitanti_RO_20261013T085058369954Z' / 'firme_clasificate_COMPANY.csv'
# Keep this name to resume the same dataset. Change it after a PATSTAT edition change.
RUN_NAME = 'company_bibliografie_esantion_10_v1'
PAGE_SIZE = 500
APP_BATCH = 25

def encode(x):
    if hasattr(x, 'isoformat'): return x.isoformat()
    if hasattr(x, 'item'): return x.item()
    raise TypeError(str(type(x)))

def atomic_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, default=encode), encoding='utf-8')
    tmp.replace(path)

if not INPUT.exists():
    raise FileNotFoundError(f'Nu gasesc {INPUT}. Modifica INPUT cu calea CSV-ului COMPANY.')
inventory = pd.read_csv(INPUT, dtype=str, keep_default_na=False)
# Deterministic sample: first 10 applicant records ordered by person_id.
# PATSTAT records are not guaranteed to be distinct legal companies.
inventory = inventory.assign(_sort_id=inventory['person_id'].astype('int64')).sort_values('_sort_id').head(10).drop(columns='_sort_id').copy()
ids = sorted(set(int(x) for x in inventory['person_id']))
print('Cele 10 inregistrari selectate:', flush=True)
display(inventory[['person_id','person_name','person_ctry_code','psn_sector']])
if len(ids) != len(inventory): raise ValueError('person_id duplicat in inventar')
if not inventory['psn_sector'].str.contains(r'\bCOMPANY\b', regex=True).all():
    raise ValueError('Selecteaza fisierul COMPANY, nu inventarul general.')
OUT = Path.home() / RUN_NAME
OUT.mkdir(exist_ok=True)
CACHE = OUT / 'checkpoint'
CACHE.mkdir(exist_ok=True)
state_path = OUT / 'manifest.json'
signature = hashlib.sha256(INPUT.read_bytes() + json.dumps(ids).encode()).hexdigest()
inventory.to_csv(OUT / 'selectie_10.csv', index=False, encoding='utf-8-sig')
state = json.loads(state_path.read_text()) if state_path.exists() else {}
if state and state.get('input_sha256') != signature:
    raise ValueError('Inventar schimbat: alege alt RUN_NAME.')
state.update(status='running', input_sha256=signature, input_records=len(ids),
    source='PATSTAT PROD via TIP',
    limits=['Same PATSTAT edition required when resuming; edition is not automatically verified.',
            'COMPANY classification is not a unique-company or current-ownership certification.',
            'Family publications use DOCDB family, not a guaranteed exact copy of Espacenet Published as.',
            'CPC symbols do not include Espacenet office attribution such as EP/US.',
            'Missing titles/abstracts remain empty; no family abstract substitution or translation.',
            'No full text, PDF, finance or CUI retrieval. No claim of live Espacenet completeness.'])
atomic_json(state_path,state)
print(f'Selectie: {len(ids)} inregistrari COMPANY. Folder: {OUT}', flush=True)
print('Conectare PROD...',flush=True)
client = PatstatClient(env='PROD')
db = client.orm()

def read(model_name, fields, key, values, applicant_only=False):
    """Read distinct scalar rows, not ORM entity PKs. Cache only count-checked results."""
    values = sorted(set(int(v) for v in values if int(v)>0))
    if not values: return []
    model = getattr(M,model_name)
    cols = [getattr(model,f) for f in fields]
    query_id = [model_name,fields,key,values,applicant_only]
    cache = CACHE / (hashlib.sha256(json.dumps(query_id).encode()).hexdigest()+'.json')
    if cache.exists():
        saved=json.loads(cache.read_text(encoding='utf-8'))
        if saved['count']!=len(saved['rows']): raise ValueError('Checkpoint invalid')
        return saved['rows']
    print(f'  {model_name}: {len(values)} identificatori',flush=True)
    q = db.query(*cols).filter(getattr(model,key).in_(values))
    if applicant_only: q=q.filter(model.applt_seq_nr>0)
    q=q.distinct()
    data=[];seen=set();offset=0
    while True:
        frame=client.df(q.order_by(*cols).offset(offset).limit(PAGE_SIZE))
        if frame.empty:break
        rows=json.loads(frame.to_json(orient='records',date_format='iso'))
        for row in rows:
            token=json.dumps(row,sort_keys=True)
            if token in seen:raise RuntimeError(f'{model_name}: repeated full row across pages; stopped, not silently truncated.')
            seen.add(token)
        data.extend(rows);offset+=len(rows)
        print(f'    {offset} randuri citite',flush=True)
    count=int(client.df(db.query(func.count().label('n')).select_from(q.order_by(None).subquery())).iloc[0,0])
    if count!=len(data):raise RuntimeError(f'{model_name}: count mismatch {count} vs {len(data)}')
    atomic_json(cache,{'count':count,'rows':data})
    return data

def grouped(rows,key):
    result={}
    for row in rows:result.setdefault(int(row[key]),[]).append(row)
    return result

def get_apps(values):
    return read('TLS201_APPLN',['appln_id','appln_auth','appln_nr','appln_kind','appln_filing_date','docdb_family_id'],'appln_id',values)

def compact_app(r):
    return {'appln_id':r['appln_id'],'office':r['appln_auth'],'number':r['appln_nr'],
            'kind':r['appln_kind'],'date':r['appln_filing_date']}

def compact_pub(r):
    return {'publication':str(r['publn_auth'])+str(r['publn_nr'])+str(r['publn_kind']),
            'date':r['publn_date'],'appln_id':r['appln_id']}

PUB_FIELDS=['appln_id','pat_publn_id','publn_auth','publn_nr','publn_kind','publn_date']
try:
    links=[]
    for start in range(0,len(ids),100):
        print(f'Identificare cereri: {min(start+100,len(ids))}/{len(ids)} solicitanti',flush=True)
        links.extend(read('TLS207_PERS_APPLN',['person_id','appln_id'],'person_id',ids[start:start+100],True))
    app_ids=sorted(set(int(r['appln_id']) for r in links))
    company_links=grouped(links,'appln_id')
    matched={int(r['person_id']) for r in links}
    state['applicants_without_links']=sorted(set(ids)-matched)
    state['selected_applications']=len(app_ids)
    state['completed_applications']=0
    state['missing_titles']=0;state['missing_abstracts']=0
    state['missing_application_records']=[]
    atomic_json(state_path,state)
    print(f'{len(app_ids)} cereri distincte. Incep bibliografia.',flush=True)
    # Rebuilt from cached validated queries on each run, avoiding duplicate output rows.
    with (OUT/'brevete_COMPANY.jsonl').open('w',encoding='utf-8') as jf, (OUT/'brevete_COMPANY.csv').open('w',encoding='utf-8-sig',newline='') as cf:
        fields=['appln_id','matched_company_person_ids','titles','abstracts','applicants','inventors','ipc','cpc','priorities','application','publications','published_as_docdb_family']
        writer=csv.DictWriter(cf,fieldnames=fields);writer.writeheader()
        for start in range(0,len(app_ids),APP_BATCH):
            selected=app_ids[start:start+APP_BATCH]
            print(f'Bibliografie: cereri {start+1}-{start+len(selected)}/{len(app_ids)}',flush=True)
            apps=get_apps(selected)
            state['missing_application_records'].extend(sorted(set(selected)-{int(r['appln_id']) for r in apps}))
            titles=grouped(read('TLS202_APPLN_TITLE',['appln_id','appln_title_lg','appln_title'],'appln_id',selected),'appln_id')
            abstracts=grouped(read('TLS203_APPLN_ABSTR',['appln_id','appln_abstract_lg','appln_abstract'],'appln_id',selected),'appln_id')
            roles=grouped(read('TLS207_PERS_APPLN',['appln_id','person_id','applt_seq_nr','invt_seq_nr'],'appln_id',selected),'appln_id')
            person_ids={int(r['person_id']) for rs in roles.values() for r in rs}
            persons={}
            ordered=sorted(person_ids)
            for pos in range(0,len(ordered),250):
                for r in read('TLS206_PERSON',['person_id','person_name','person_ctry_code'],'person_id',ordered[pos:pos+250]):persons[int(r['person_id'])]=r
            ipc=grouped(read('TLS209_APPLN_IPC',['appln_id','ipc_class_symbol'],'appln_id',selected),'appln_id')
            cpc=grouped(read('TLS224_APPLN_CPC',['appln_id','cpc_class_symbol'],'appln_id',selected),'appln_id')
            priorities=grouped(read('TLS204_APPLN_PRIOR',['appln_id','prior_appln_id','prior_appln_seq_nr'],'appln_id',selected),'appln_id')
            pri_ids={int(r['prior_appln_id']) for rs in priorities.values() for r in rs}
            pri_apps={int(r['appln_id']):r for r in get_apps(pri_ids)}
            pubs=grouped(read('TLS211_PAT_PUBLN',PUB_FIELDS,'appln_id',selected),'appln_id')
            families={int(r['docdb_family_id']) for r in apps if r['docdb_family_id'] and int(r['docdb_family_id'])>0}
            fam_apps=read('TLS201_APPLN',['appln_id','docdb_family_id'],'docdb_family_id',families)
            app_family={int(r['appln_id']):int(r['docdb_family_id']) for r in fam_apps}
            fam_pubs={}
            family_ids=sorted(app_family)
            for pos in range(0,len(family_ids),250):
                for r in read('TLS211_PAT_PUBLN',PUB_FIELDS,'appln_id',family_ids[pos:pos+250]):
                    fam_pubs.setdefault(app_family[int(r['appln_id'])],[]).append(compact_pub(r))
            for a in apps:
                aid=int(a['appln_id'])
                def people(role):
                    result=[]
                    for rel in sorted(roles.get(aid,[]),key=lambda r:(int(r[role]),int(r['person_id']))):
                        if int(rel[role])>0:
                            pid=int(rel['person_id']);p=persons.get(pid,{})
                            result.append({'person_id':pid,'name':p.get('person_name'),'country':p.get('person_ctry_code'),'sequence':rel[role]})
                    return result
                row={'appln_id':aid,'matched_company_person_ids':sorted({int(r['person_id']) for r in company_links[aid]}),
                     'titles':[{'language':r['appln_title_lg'],'text':r['appln_title']} for r in titles.get(aid,[])],
                     'abstracts':[{'language':r['appln_abstract_lg'],'text':r['appln_abstract']} for r in abstracts.get(aid,[])],
                     'applicants':people('applt_seq_nr'),'inventors':people('invt_seq_nr'),
                     'ipc':[r['ipc_class_symbol'].strip() for r in ipc.get(aid,[])],
                     'cpc':[r['cpc_class_symbol'].strip() for r in cpc.get(aid,[])],
                     'priorities':[{'sequence':r['prior_appln_seq_nr'],'application':compact_app(pri_apps[int(r['prior_appln_id'])]) if int(r['prior_appln_id']) in pri_apps else {'appln_id':r['prior_appln_id'],'missing':True}} for r in priorities.get(aid,[])],
                     'application':compact_app(a),'publications':[compact_pub(r) for r in pubs.get(aid,[])],
                     'published_as_docdb_family':fam_pubs.get(int(a['docdb_family_id'] or 0),[])}
                jf.write(json.dumps(row,ensure_ascii=False,default=encode)+'\n')
                writer.writerow({k:json.dumps(v,ensure_ascii=False,default=encode) if isinstance(v,(list,dict)) else v for k,v in row.items()})
                state['completed_applications']+=1
                state['missing_titles']+=not bool(row['titles']);state['missing_abstracts']+=not bool(row['abstracts'])
            jf.flush();cf.flush();atomic_json(state_path,state)
    state['status']='completed_with_missing_application_records' if state['missing_application_records'] else 'completed_selected_scope'
    state['finished_utc']=datetime.now(timezone.utc).isoformat()
    state.pop('last_error',None);atomic_json(state_path,state)
except BaseException as exc:
    state['status']='interrupted_or_failed';state['last_error']=repr(exc);atomic_json(state_path,state)
    print('OPRIT:',repr(exc),'\nPoti relua aceeasi celula dupa rezolvarea erorii. Checkpoint-urile verificate se reutilizeaza.',flush=True)
    raise
else:
    # Download only the final data and manifest, not the query cache.
    import zipfile
    archive=OUT/'rezultat_COMPANY.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as z:
        for name in ['selectie_10.csv','brevete_COMPANY.csv','brevete_COMPANY.jsonl','manifest.json']:z.write(OUT/name,arcname=name)
    print('FINALIZAT:',state['completed_applications'],'cereri. Fara rezumat:',state['missing_abstracts'],flush=True)
    display(FileLink(str(archive)))
