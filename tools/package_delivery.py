from pathlib import Path
import hashlib
import json
import zipfile

repository = Path(__file__).resolve().parents[1]
root = (repository / '隐盾整合交付_20261012').resolve()
target = root.with_suffix('.zip')
manifest = root / '交付文件清单.json'
assert root.parent == repository
assert root.is_dir()
assert (root / 'runtime/python/python.exe').is_file(), 'Portable runtime is local-only. Use the Git setup script when no runtime is installed.'

# Read only the distributable template. Never copy the user's working .env.
safe_env = (root / 'app/.env.example').read_bytes()
config = {}
for line in safe_env.decode('utf-8-sig').splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k, v = line.split('=', 1)
        config[k.strip()] = v.strip().strip('\"\'')
assert config.get('LLM_MODE') == 'mock'
for k, v in config.items():
    if any(part in k.upper() for part in ('KEY', 'TOKEN', 'PASSWORD', 'SECRET')):
        assert not v, f'Refusing to package nonempty credential setting: {k}'

summary_path = root / '验证结果/验证摘要.json'
summary = json.loads(summary_path.read_text(encoding='utf-8'))
assert summary['report_visual_qa']['all_pages_inspected'] is True
summary['browser_checks'] = json.loads((root / '验证结果/网页交互检查.json').read_text(encoding='utf-8'))
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

trial_meta = json.loads((root / '人工复核/当前试标.json').read_text(encoding='utf-8'))
trial_path = (root / trial_meta['directory']).resolve()
assert trial_path.is_relative_to(root / '人工复核/试标运行')
trial = json.loads((trial_path / 'evidence.json').read_text(encoding='utf-8'))
assert trial['mode'] == 'mock' and trial['dataset'] == 'synthetic_trial_not_human_gold'
assert trial['weights_sha256'] == hashlib.sha256((root / 'app/models/necessity_action.joblib').read_bytes()).hexdigest()
review_assets = {root / '人工复核/当前试标.json', root / '人工复核/使用说明.md', root / '人工复核/第二台电脑验收.md',
                 trial_path / 'evidence.json', trial_path / '独立复核.html'}

def eligible(path):
    rel = path.relative_to(root)
    if path == manifest or path.is_symlink():
        return False
    if any(part in {'__pycache__', '.pytest_cache', '.git', '.venv'} or part.startswith('pytest-cache-files-') for part in rel.parts):
        return False
    if path.suffix.lower() in {'.pyc', '.pyo', '.log'} or path.name.startswith('~$'):
        return False
    if path.name == '.env' or (path.name.startswith('.env.') and path.name != '.env.example'):
        return False
    # Only fixed synthetic trial assets may be shared, never saved human annotations.
    if rel.parts[0] == '人工复核' and path not in review_assets:
        return False
    # Generated traces and uploaded private content are not distributable assets.
    if rel.parts[:2] == ('app', 'outputs'):
        return False
    if rel.parts[:3] == ('app', 'data', 'uploads') and path.name != '.gitkeep':
        return False
    return path.is_file()

files = sorted(p for p in root.rglob('*') if eligible(p))
records = []
for path in files:
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    records.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest})
records.append({'path': 'app/.env', 'bytes': len(safe_env), 'sha256': hashlib.sha256(safe_env).hexdigest()})
manifest.write_text(json.dumps({'date': '2026-10-13', 'files': records, 'excluded': ['Python and pytest caches', 'runtime traces', 'uploaded content', 'working credentials', 'human review records'], 'note': 'Manifest describes the ZIP, excluding itself. ZIP app/.env is generated from the empty-key mock template; the working .env is preserved.'}, ensure_ascii=False, indent=2), encoding='utf-8')
with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
    for path in [*files, manifest]:
        bundle.write(path, root.name + '/' + path.relative_to(root).as_posix())
    bundle.writestr(root.name + '/app/.env', safe_env)
with zipfile.ZipFile(target) as bundle:
    invalid = bundle.testzip()
    assert invalid is None, invalid
    for record in records:
        info = bundle.getinfo(root.name + '/' + record['path'])
        assert info.file_size == record['bytes']
        assert hashlib.sha256(bundle.read(info)).hexdigest() == record['sha256']
    assert bundle.read(root.name + '/app/.env') == safe_env
    assert not any('/data/uploads/' in n and not n.endswith('/.gitkeep') for n in bundle.namelist())
with target.open('rb') as f:
    zip_hash = hashlib.file_digest(f, 'sha256').hexdigest()
target.with_suffix('.zip.sha256').write_text(zip_hash + '  ' + target.name + '\n', encoding='utf-8')
print(json.dumps({'files_in_archive': len(files) + 2, 'archive_bytes': target.stat().st_size, 'zip_crc_and_hashes_verified': True, 'sha256': zip_hash, 'output': str(target)}, ensure_ascii=False))
