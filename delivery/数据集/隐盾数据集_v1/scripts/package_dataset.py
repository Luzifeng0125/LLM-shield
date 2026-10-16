"""Package only the dataset, preserving provenance and refusing filled human reviews."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
    target=args.out.resolve()
    if target.exists() or target.is_relative_to(ROOT):
        raise SystemExit('Choose a new ZIP path outside the dataset folder; existing files are not overwritten.')
    subprocess.run([sys.executable,'-B',str(ROOT/'scripts/validate_dataset.py')],check=True,stdout=subprocess.DEVNULL)
    for name in ('reviewer_A.jsonl','reviewer_B.jsonl'):
        for line in (ROOT/'review'/name).read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            if row.get('reviewed') or row.get('notes') or any(row.get(k) is not None for k in ('human_entities','human_action','human_turn_targets')):
                raise SystemExit('Filled human review data found; refusing to distribute it automatically.')
    files=[]
    for p in ROOT.rglob('*'):
        if p.is_symlink(): raise SystemExit('Unexpected symbolic link in dataset')
        if not p.is_file() or '__pycache__' in p.parts or p.suffix=='.pyc' or p.name=='manifest.json': continue
        if p.parent.name=='review' and ('gold' in p.name or p.name.startswith('adjudicated')): continue
        files.append(p)
    files.sort()
    entries=[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
    manifest=ROOT/'manifest.json'
    manifest.write_text(json.dumps({'version':'1.0','date':'2026-10-14','files':entries,'note':'Manifest excludes itself; original and converted formats contain duplicate views of the same examples.'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files+[manifest]: z.write(p,ROOT.name+'/'+p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for e in entries: assert hashlib.sha256(z.read(ROOT.name+'/'+e['path'])).hexdigest()==e['sha256']
    sha=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix+'.sha256').write_text(sha+'  '+target.name+'\n',encoding='utf-8')
    print(json.dumps({'zip':str(target),'files':len(files)+1,'bytes':target.stat().st_size,'sha256':sha,'crc_and_file_hashes_verified':True},ensure_ascii=False))

if __name__=='__main__': main()
