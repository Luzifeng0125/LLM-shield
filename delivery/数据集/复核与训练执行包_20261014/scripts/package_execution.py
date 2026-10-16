"""Package only pristine operational materials; exclude QA fixtures and real work."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
out=ROOT.parents[2]/'隐盾复核与训练执行包_20261014.zip'
if out.exists():raise SystemExit('Refusing to overwrite existing zip')
for path in (ROOT/'批次').glob('*/复核员*/空白复核表.jsonl'):
    rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s]
    if any(r['reviewed'] or r['notes'] for r in rows):raise SystemExit('Human work detected')
    for r in rows:
        aa=r['annotation']['turns'] if r['kind']=='dialogue' else [r['annotation']]
        if any(a['entities'] or (a.get('target') and (a['target']['preferred_action'] or a['target']['reason'] or a['target']['acceptable_actions'] or a['target']['sanitized_text'] is not None)) for a in aa):
            raise SystemExit('Nonempty human annotation detected')
files=[p for p in ROOT.rglob('*') if p.is_file() and not any(part in {'qa','gold','工作结果','__pycache__'} for part in p.relative_to(ROOT).parts) and p.name!='交付清单.json']
manifest={'created_date':'2026-10-14','human_gold_count':0,'review_units':312,'independent_reviewers':2,
          'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]}
mp=ROOT/'交付清单.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');files.append(mp)
with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,ROOT.name+'/'+p.relative_to(ROOT).as_posix())
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
    for row in manifest['files']:
        assert hashlib.sha256(z.read(ROOT.name+'/'+row['path'])).hexdigest()==row['sha256']
sha=hashlib.sha256(out.read_bytes()).hexdigest()
out.with_suffix('.zip.sha256').write_text(sha+'  '+out.name+'\n',encoding='utf-8')
print(json.dumps({'zip':str(out),'files':len(files),'bytes':out.stat().st_size,'sha256':sha},ensure_ascii=False))
