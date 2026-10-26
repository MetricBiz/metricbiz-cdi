"""Run in EPO TIP: applicant inventory, NOT the complete patent export."""
from pathlib import Path
from datetime import datetime, timezone
import json
import shutil
import pandas as pd
from sqlalchemy import func
from epo.tipdata.patstat import PatstatClient
from epo.tipdata.patstat.database.models import TLS206_PERSON as P, TLS207_PERS_APPLN as PA
from IPython.display import FileLink, display

print('Conectare PATSTAT PROD...', flush=True)
client_ro = PatstatClient(env='PROD')
session_ro = client_ro.orm()
folder_ro = Path('solicitanti_RO_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
folder_ro.mkdir()
manifest_ro = {'status': 'running', 'scope': 'RO persons with applicant role applt_seq_nr > 0',
               'source': 'PATSTAT Global PROD via TIP', 'rows': 0,
               'note': 'One person_id is not necessarily one company. No CUI/ownership confirmation.'}

def save_status():
    (folder_ro / 'manifest.json').write_text(json.dumps(manifest_ro, indent=2), encoding='utf-8')

save_status()
columns_ro = list(P.__table__.columns)
has_application = session_ro.query(PA.person_id).filter(
    PA.person_id == P.person_id, PA.applt_seq_nr > 0).exists()
base_ro = session_ro.query(*columns_ro).filter(P.person_ctry_code == 'RO', has_application)
last_id_ro = -1
pages_ro = []
try:
    while True:
        print(f'Citesc lotul dupa person_id={last_id_ro}...', flush=True)
        page_ro = client_ro.df(base_ro.filter(P.person_id > last_id_ro).order_by(P.person_id).limit(1000))
        if page_ro.empty:
            break
        ids_ro = page_ro['person_id'].astype('int64')
        if ids_ro.duplicated().any() or not ids_ro.is_monotonic_increasing or int(ids_ro.min()) <= last_id_ro:
            raise RuntimeError('Pagination validation failed')
        page_ro.to_csv(folder_ro / f'lot_{len(pages_ro)+1:05d}.csv', index=False, encoding='utf-8-sig')
        pages_ro.append(page_ro)
        last_id_ro = int(ids_ro.max())
        manifest_ro['rows'] += len(page_ro)
        save_status()
        print(f"Salvate {manifest_ro['rows']} inregistrari", flush=True)

    records_ro = pd.concat(pages_ro, ignore_index=True) if pages_ro else pd.DataFrame(columns=[c.name for c in columns_ro])
    records_ro.to_csv(folder_ro / 'toti_solicitantii_RO.csv', index=False, encoding='utf-8-sig')
    sectors_ro = records_ro['psn_sector'].fillna('').str.upper()
    company_ro = sectors_ro.str.contains(r'\bCOMPANY\b', regex=True)
    records_ro[company_ro].to_csv(folder_ro / 'firme_clasificate_COMPANY.csv', index=False, encoding='utf-8-sig')
    records_ro[~company_ro].to_csv(folder_ro / 'ceilalti_solicitanti_de_verificat.csv', index=False, encoding='utf-8-sig')
    manifest_ro['company_classified_records'] = int(company_ro.sum())
    manifest_ro['status'] = 'exported_pending_count_validation'
    save_status()
    print('Datele sunt salvate. Verific totalul din sursa...', flush=True)
    n_ro = client_ro.df(session_ro.query(func.count(P.person_id).label('n')).filter(
        P.person_ctry_code == 'RO', has_application))
    manifest_ro['source_count'] = int(n_ro.iloc[0, 0])
    if manifest_ro['source_count'] != len(records_ro):
        raise RuntimeError('Source count differs from exported count')
    manifest_ro['status'] = 'count_verified'
except BaseException as exc:
    manifest_ro['error'] = repr(exc)
    manifest_ro['status'] = 'incomplete_or_unverified'
    save_status()
    print('Export incomplet sau neverificat; loturile deja salvate raman in', folder_ro, flush=True)
    raise
else:
    save_status()
    zip_ro = shutil.make_archive(str(folder_ro), 'zip', folder_ro)
    print('FINALIZAT:', len(records_ro), 'inregistrari de solicitanti; NU numar de firme unice.', flush=True)
    display(FileLink(zip_ro))
