"""Offline check: pip install jsonschema==4.26.0; run with --c3-root <checkout>.

The Android unit test pins these whole snapshots to the production mapper.
This check uses the supplied local C3 parser, not a deployed device or its store.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c3-root', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    paths = {
        'appSchema': root / 'protocol/navassist-v3.schema.json',
        'androidFixtures': root / 'app/src/test/resources/navassist/android-snapshots.json',
        'c3Schema': args.c3_root / 'openpilot/sunnypilot/navassist/nav-assist-v3.schema.json',
        'c3Parser': args.c3_root / 'openpilot/sunnypilot/navassist/protocol.py',
        'androidMapper': root / 'app/src/main/kotlin/com/garan/tesnav/export/NavAssistV2Protocol.kt',
    }
    schemas = [json.loads(paths[key].read_text(encoding='utf-8')) for key in ('appSchema', 'c3Schema')]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    check(schemas[0] == schemas[1], 'App and selected local C3 schemas differ; review the target version')
    validators = [Draft202012Validator(schema) for schema in schemas]
    spec = importlib.util.spec_from_file_location('contract_c3_protocol', paths['c3Parser'])
    receiver = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = receiver
    spec.loader.exec_module(receiver)
    fixtures = json.loads(paths['androidFixtures'].read_text(encoding='utf-8'))
    results = []

    def verify(name, payload, valid=True):
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        check(len(body) <= 8192, f'{name}: exceeds UDP snapshot limit')
        schema_results = [validator.is_valid(payload) for validator in validators]
        try:
            parsed = receiver.parse_snapshot(body)
            accepted = True
        except receiver.NavAssistProtocolError:
            parsed, accepted = None, False
        check(schema_results == [valid, valid] and accepted == valid,
              f'{name}: expected {valid}, schemas={schema_results}, C3={accepted}')
        results.append({'case': name, 'accepted': valid, 'bytes': len(body)})
        return parsed

    for name, payload in fixtures.items():
        parsed = verify(name, payload)
        check(parsed.route_active == (name == 'realtime'), f'{name}: active state changed')
        check((parsed.maneuver_event_id > 0) == (name == 'realtime'), f'{name}: event changed')
    realtime = fixtures['realtime']
    parsed = receiver.parse_snapshot(json.dumps(realtime, ensure_ascii=False).encode('utf-8'))
    check(parsed.lanes[0].route_avoid and not parsed.lanes[1].route_avoid, 'routeAvoid lost')
    check((parsed.parallel_road_status, parsed.elevated_road_status, parsed.route_notice_type,
           parsed.route_notice_distance_m, parsed.route_notice_observed_at_ms) ==
          ('main', 'side', 'road_closed', 350.0, 2100), 'guidance extensions lost')
    check((parsed.next_maneuver, parsed.next_maneuver_distance_m) == ('turn_left', 480.0),
          'next maneuver lost between App snapshot and C3 parser')

    def changed(path, value):
        payload = copy.deepcopy(realtime)
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return payload

    for key in ('parallelRoadStatus', 'elevatedRoadStatus', 'routeNoticeType'):
        definition = schemas[1]['$defs']['guidance']['properties'][key]
        for value in definition['enum']:
            verify(f'{key}={value}', changed(('guidance', key), value))
        for value in (None, True, 1, 'unsupported'):
            verify(f'invalid {key}={value}', changed(('guidance', key), value), False)
    for key in ('routeNoticeDistanceM', 'routeNoticeObservedAtMs'):
        maximum = 100000 if key.endswith('DistanceM') else 2**63 - 1
        for value in (0, maximum):
            verify(f'{key}={value}', changed(('guidance', key), value))
        for value in (None, True, '1', -1, 1.5):
            verify(f'invalid {key}={value}', changed(('guidance', key), value), False)
    verify('distance overflow', changed(('guidance', 'routeNoticeDistanceM'), 100001), False)
    for value in (True, False):
        verify(f'routeAvoid={value}', changed(('lanes', 'items', 0, 'routeAvoid'), value))
    for value in (None, 0, 1, 'false'):
        verify(f'invalid routeAvoid={value}', changed(('lanes', 'items', 0, 'routeAvoid'), value), False)
    for path in (('unexpected',), ('guidance', 'unexpected'), ('lanes', 'items', 0, 'unexpected')):
        verify(f'unknown {path}', changed(path, True), False)
    legacy = copy.deepcopy(realtime)
    for key in ('parallelRoadStatus', 'elevatedRoadStatus', 'routeNoticeType',
                'routeNoticeDistanceM', 'routeNoticeObservedAtMs'):
        del legacy['guidance'][key]
    for lane in legacy['lanes']['items']:
        del lane['routeAvoid']
    verify('optional extensions absent', legacy)

    report = {
        'files': {key: {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                  for key, path in paths.items()},
        'cases': results,
        'scope': 'Local schemas and parser only; not store freshness, ownership, SDK provenance or deployed compatibility.',
    }
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: {len(results)} whole-packet checks against both schemas and the local C3 parser')


if __name__ == '__main__':
    main()
