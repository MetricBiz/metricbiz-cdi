# MetricBiz EPO Extraction

Scripturi Python în notebook-uri Jupyter, rulate în platforma EPO TIP și conectate la PATSTAT Global PROD, pentru extragerea solicitanților din România și a datelor bibliografice despre cererile de brevet.

## 1. Export_solicitanti_RO.ipynb

Extrage înregistrările cu țara RO care apar ca solicitanți în cereri de brevet.

La rularea efectuată am obținut:
- 33.552 de înregistrări de solicitanți;
- 6.670 de înregistrări clasificate COMPANY;
- 26.882 de alte înregistrări, păstrate pentru verificare.

Salvează inventarul complet și cele două selecții în fișiere CSV, împreună cu un manifest și o arhivă ZIP.

Înregistrările nu reprezintă automat firme distincte. Inventarul include și persoane fizice sau instituții, iar person_id este un identificator PATSTAT, nu CUI.

## 2. Export_COMPANY_esantion_10.ipynb

Folosește inventarul din prima etapă și selectează primele 10 înregistrări COMPANY, ordonate după person_id.

Identifică cererile asociate și extrage:
- titlurile și rezumatele, cu limbile disponibile;
- solicitanții și inventatorii;
- clasificările IPC și CPC;
- numărul și data cererii;
- prioritățile;
- publicațiile cererii;
- publicațiile asociate familiei DOCDB.

Testul s-a finalizat cu 14 cereri distincte, toate având rezumat.

Rezultatele sunt salvate în CSV și JSONL, împreună cu selecția utilizată și manifestul execuției, în arhiva rezultat_COMPANY.zip.

## Ordinea de rulare

1. Rulăm Export_solicitanti_RO.ipynb în EPO TIP.
2. Păstrăm folderul rezultat în platformă.
3. Verificăm calea către inventar în notebook-ul pentru eșantion.
4. Rulăm Export_COMPANY_esantion_10.ipynb.

Notebook-urile necesită acces la EPO TIP și PATSTAT. Încărcarea lor în GitHub nu le execută.

## Limite

Exportul bibliografic a fost validat pe eșantionul de 10 înregistrări COMPANY, nu pe întreaga selecție.

Datele nu includ CUI, documentele integrale ale brevetelor sau dovada titularului actual. O cerere de brevet nu confirmă automat acordarea brevetului ori exploatarea comercială.

Repository-ul păstrează codul. Fișierele cu date extrase și credențialele se păstrează separat.
