"""Reproducible local run: LLM extraction, official server, coordinator, evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'runs' / 'runtime'))


def default_data():
    for ancestor in [ROOT, *ROOT.parents]:
        for relative in ('data/package/hack_the_highway_package/data',
                         'challenges/challenge-6/data/package/hack_the_highway_package/data'):
            candidate = ancestor / relative
            if (candidate / 'events.json').exists():
                return candidate
    return ROOT / 'data'


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def validate_cached_record(record, event, graph):
    """A cache is evidence, not authority: rederive facts from its raw model output."""
    from src.parse import normalize_incidents, parse_json_output
    if record.get('text_sha256') != hashlib.sha256(event['text'].encode()).hexdigest():
        raise ValueError('Parsed text hash mismatch; fresh LLM extraction required.')
    provenance = record.get('provenance', {})
    if not provenance.get('raw_output'):
        raise ValueError('Parsed event lacks LLM output provenance.')
    if provenance.get('provider') == 'gemini' and provenance.get('finish_reason') != 'STOP':
        raise ValueError('Cached Gemini extraction did not complete normally.')
    derived = normalize_incidents(parse_json_output(provenance['raw_output']), event['text'], graph)
    if derived != record.get('incidents'):
        raise ValueError('Cached incidents differ from current normalization of raw LLM output; revalidate first.')
    if provenance.get('warnings') or any(i.get('reason', '').startswith('Extraction validation failed') for i in derived):
        raise ValueError('Cached extraction has validation warnings.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=default_data())
    ap.add_argument('--model', type=Path, default=ROOT / 'runs/models/qwen2.5-1.5b-instruct')
    ap.add_argument('--provider', choices=('gemini', 'local'), default='gemini')
    ap.add_argument('--model-name', help='Optional Gemini model; verified against live catalog.')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--parsed-file', type=Path, help='Reuse recorded LLM output with matching event-text hashes.')
    ap.add_argument('--extract-only', action='store_true')
    ap.add_argument('--port', type=int, default=8606)
    ap.add_argument('--overwrite', action='store_true')
    args = ap.parse_args()
    args.out = args.out.resolve()
    if (args.out / 'action_log.jsonl').exists() and not args.overwrite:
        raise SystemExit('Output already has an action log; choose a fresh directory or explicit --overwrite.')
    args.out.mkdir(parents=True, exist_ok=True)
    from src.graph import KnowledgeGraph
    graph = KnowledgeGraph(args.data)
    events = json.loads((args.data / 'events.json').read_text(encoding='utf-8'))
    hashes = {e['event_id']: hashlib.sha256(e['text'].encode()).hexdigest() for e in events}
    if args.parsed_file:
        parsed = json.loads(args.parsed_file.read_text(encoding='utf-8'))
        if {p['event_id'] for p in parsed} != set(hashes) or len(parsed) != len(events):
            raise SystemExit('Parsed event set does not match feed.')
        by_event_id = {event['event_id']: event for event in events}
        for record in parsed:
            validate_cached_record(record, by_event_id[record['event_id']], graph)
    else:
        from src.parse import EventParser
        parser = EventParser(graph, model_path=args.model, provider=args.provider, model_name=args.model_name)
        parsed = []
        for event in events:
            record = parser.parse(event)
            record['text_sha256'] = hashes[event['event_id']]
            parsed.append(record)
            dump(args.out / 'parsed.json', parsed)
            print(json.dumps({'event': event['event_id'], 'incidents': record['incidents'],
                              'extracted': len(parsed)}, ensure_ascii=False), flush=True)
        if any(record.get('provenance', {}).get('warnings') for record in parsed):
            raise SystemExit('Extraction has validation warnings; review parsed.json before executing any writes.')
        del parser
        import gc
        gc.collect()
    dump(args.out / 'parsed.json', parsed)
    if any(record.get('provenance', {}).get('warnings') for record in parsed):
        raise SystemExit('Recorded extraction has validation warnings; review before execution.')
    dump(args.out / 'events.json', events)
    if args.extract_only:
        return
    from src.client import EnterpriseClient
    from src.agents import Coordinator
    server_script = ROOT / 'starter' / 'enterprise_server.py'
    command = [sys.executable, str(server_script), '--data', str(args.data),
               '--events', str(args.data / 'events.json'), '--out', str(args.out), '--port', str(args.port)]
    if args.overwrite:
        command.append('--overwrite')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    started = time.perf_counter()
    with (args.out / 'server.stdout.log').open('w', encoding='utf-8') as output:
        server = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                  creationflags=flags, cwd=ROOT)
        try:
            base = f'http://127.0.0.1:{args.port}'
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Official server exited; inspect server.stdout.log')
                try:
                    with urlopen(base + '/tools', timeout=1) as response:
                        tools = json.load(response)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError('Official server did not become reachable')
            client = EnterpriseClient(base, log_path=args.out / 'client_audit.jsonl')
            coordinator = Coordinator(graph, client)
            traces = []
            by_id = {record['event_id']: record for record in parsed}
            for event in events:
                trace = coordinator.handle(event, by_id[event['event_id']])
                traces.append(trace)
                dump(args.out / 'traces.json', traces)
                print(json.dumps({'event': event['event_id'], 'status': trace['status'],
                                  'writes': trace.get('write_count', 0)}), flush=True)
                if trace['status'] in ('halted', 'needs_review'):
                    raise RuntimeError(f"Event {event['event_id']} requires review; stopping the run.")
            records = [json.loads(line) for line in (args.out / 'action_log.jsonl').read_text().splitlines()]
            summary = {'events': len(traces), 'server_calls': len(records),
                       'failed_calls': sum(not r['ok'] for r in records),
                       'operational_writes': sum(t.get('write_count', 0) for t in traces),
                       'seconds_execution': round(time.perf_counter() - started, 3),
                       'tool_count': len(tools), 'source_hashes': graph.source_hashes,
                       'event_text_hashes': hashes, 'parsed_file_reused': bool(args.parsed_file)}
            summary['models'] = sorted({p['provenance']['model'] for p in parsed})
            summary['llm_input_tokens'] = sum(p['provenance'].get('input_tokens') or 0 for p in parsed)
            summary['llm_output_tokens'] = sum(p['provenance'].get('output_tokens') or 0 for p in parsed)
            summary['llm_seconds'] = round(sum(p['provenance'].get('latency_seconds') or 0 for p in parsed), 3)
            summary['code_sha256'] = {str(path.relative_to(ROOT)).replace('\\', '/'):
                hashlib.sha256(path.read_bytes()).hexdigest()
                for folder in ('src', 'starter') for path in (ROOT / folder).glob('*.py')}
            dump(args.out / 'summary.json', summary)
            from scripts.audit_run import audit_run
            audit = audit_run(args.data, parsed, records, traces)
            dump(args.out / 'audit.json', audit)
            print(json.dumps({k: summary[k] for k in ('events', 'server_calls', 'failed_calls',
                'operational_writes', 'seconds_execution', 'models', 'llm_input_tokens', 'llm_output_tokens')}), flush=True)
            if summary['failed_calls']:
                raise SystemExit('Run contains failed calls and must not be submitted.')
            if not audit['passed']:
                raise SystemExit('Independent audit failed; inspect audit.json before submission.')
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == '__main__':
    main()
