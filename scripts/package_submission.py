"""Package only audited artifacts and an explicit source allowlist; never include secrets."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', type=Path, default=ROOT / 'runs/submission')
    ap.add_argument('--out', type=Path, default=ROOT / 'outputs/submission')
    args = ap.parse_args()
    audit = json.loads((args.run / 'audit.json').read_text(encoding='utf-8'))
    if not audit.get('passed') or audit.get('failed_log_calls') != 0 or audit.get('events_total') != 15:
        raise SystemExit('Only a complete, independently audited 15-event run may be packaged.')
    summary = json.loads((args.run / 'summary.json').read_text(encoding='utf-8'))
    for relative, digest in summary.get('code_sha256', {}).items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise SystemExit(f'Source changed after verified run: {relative}')
    files = {}
    for name in ('action_log.jsonl', 'parsed.json', 'events.json', 'traces.json', 'summary.json', 'audit.json', 'client_audit.jsonl'):
        path = args.run / name
        if not path.is_file():
            raise SystemExit(f'Missing run artifact: {name}')
        files[name] = path
    for folder in ('src', 'scripts', 'docs', 'tests', 'starter'):
        for path in (ROOT / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.md', '.json', '.html', '.png', '.jpg', '.pdf', '.svg'):
                files['source/' + path.relative_to(ROOT).as_posix()] = path
    for name in ('README.md', 'requirements.txt', 'toolkit/prize_apis.py'):
        files['source/' + name] = ROOT / name
    original_extraction = ROOT / 'runs/extraction/raw-parsed.json'
    if original_extraction.exists():
        files['extraction/original-parsed.json'] = original_extraction
    for path in (ROOT / 'outputs/ontology').glob('*'):
        if path.is_file():
            files['ontology/' + path.name] = path
    if not any(name.startswith('ontology/') for name in files):
        raise SystemExit('Ontology export missing.')
    manifest = {name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
                for name, path in sorted(files.items())}
    args.out.mkdir(parents=True, exist_ok=True)
    destination = args.out / 'hitachi-control-tower-submission.zip'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(destination) as archive:
        bad = archive.testzip()
        if bad:
            raise SystemExit(f'ZIP integrity failure: {bad}')
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'archive': str(destination), 'files': len(manifest) + 1,
                      'bytes': destination.stat().st_size,
                      'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
