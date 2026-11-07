"""Revalidate saved, actual LLM output after a deterministic normalizer fix."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.graph import KnowledgeGraph
from src.parse import normalize_incidents, parse_json_output
from scripts.run import default_data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=default_data())
    ap.add_argument('--parsed', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.parsed.resolve() == args.out.resolve():
        raise SystemExit('Preserve the original extraction: choose a different output file.')
    graph = KnowledgeGraph(args.data)
    events = {e['event_id']: e for e in json.loads((args.data / 'events.json').read_text(encoding='utf-8'))}
    original = args.parsed.read_bytes()
    records = json.loads(original)
    for record in records:
        text = events[record['event_id']]['text']
        if record.get('text_sha256') != hashlib.sha256(text.encode()).hexdigest():
            raise SystemExit('Event source changed; a fresh extraction is required.')
        record['incidents'] = normalize_incidents(parse_json_output(record['provenance']['raw_output']), text, graph)
        provenance = record['provenance']
        provenance['original_validation_warnings'] = provenance.get('warnings', [])
        provenance['warnings'] = [i['reason'] for i in record['incidents']
                                  if i.get('reason', '').startswith('Extraction validation failed')]
        provenance['renormalized_source_sha256'] = hashlib.sha256(original).hexdigest()
        provenance['normalizer_sha256'] = hashlib.sha256((ROOT / 'src/parse.py').read_bytes()).hexdigest()
        provenance['renormalized_from_recorded_llm'] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    (args.out.parent / 'raw-parsed.json').write_bytes(original)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding='utf-8')
    warnings = sum(bool(r['provenance']['warnings']) for r in records)
    print(json.dumps({'events': len(records), 'events_with_validation_warnings': warnings,
                      'additional_llm_calls': 0, 'output': str(args.out)}))
    raise SystemExit(1 if warnings else 0)


if __name__ == '__main__':
    main()
