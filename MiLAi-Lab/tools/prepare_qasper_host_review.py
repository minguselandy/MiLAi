"""Bind autonomous QASPER Host outputs to their actual final provider inputs and source text."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from summarize_original_feedback_host import current_tools, final_provider_input, position_bank


def visible_original_ranges(
    messages: list[dict[str, Any]], sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify literal received slices; retain ambiguous identities and unsupported payloads."""
    receipts, ranges = [], []
    for message_index, message in enumerate(messages):
        if message['role'] != 'tool' or message.get('name') != 'milai_retrieve':
            continue
        receipt: dict[str, Any] = {'message_index': message_index, 'message': message}
        receipts.append(receipt)
        try:
            packet = json.loads(message['content'])
        except json.JSONDecodeError:
            receipt['status'] = 'NON_JSON_TOOL_MESSAGE_RETAINED'
            continue
        if not isinstance(packet, dict) or packet.get('schema') != 'milai_retrieval_result_v1':
            receipt.update(status='OTHER_TOOL_PAYLOAD_RETAINED', packet=packet)
            continue
        receipt.update(status='RETRIEVAL_PACKET_RETAINED', packet=packet)
        for evidence_index, evidence in enumerate(packet['evidence']):
            if evidence['kind'] != 'original_source':
                continue  # Full received payload remains in the review record, without raw proof.
            for source_index, piece in enumerate(evidence['evidence']):
                start, end = piece['range']
                matches = [s['original_event_id'] for s in sources
                    if 0 <= start <= end <= len(s['content'])
                    and s['role'] == piece['role'] and s['origin'] == piece['origin']
                    and len(s['content']) == piece['source_characters']
                    and s['content'][start:end] == piece['content']]
                ranges.append({'message_index': message_index, 'evidence_index': evidence_index,
                    'source_index': source_index, 'visible_piece': piece,
                    'original_source_candidates': matches,
                    'status': 'LITERAL_DECLARED_SOURCE_MATCH' if matches
                              else 'NO_LITERAL_INITIAL_SOURCE_MATCH_REQUIRES_REVIEW'})
    return {'visible_retrieval_receipts': receipts, 'visible_original_ranges': ranges,
        'literal_matched_ranges': sum(bool(r['original_source_candidates']) for r in ranges),
        'unmatched_ranges': sum(not r['original_source_candidates'] for r in ranges),
        'scope': 'Only actual final-input Tool receipts are enumerated here. Identical source '
            'text is not merged into one identity. Unmatched/derived material and tool errors '
            'remain visible for review; no sufficiency or answer grade is assigned. Full provider '
            'messages separately retain any initial visible material or earlier conversation.'}


def prepare(
    fixture: dict[str, Any], references: dict[str, Any], results: dict[str, str | None],
) -> dict[str, Any]:
    histories = fixture['histories']
    families = {h['source_group'] for h in histories}
    controls = {r['family']: r for r in references['cases']}
    if set(results) != families or set(controls) != families or len(families) != len(histories):
        raise ValueError(
            'Keep every declared source family exactly once, including missing results')
    records = []
    for index, history in enumerate(histories):
        request, = history['requests']
        reference = controls[history['source_group']]
        if (reference['history'] != history['id']
                or any(reference['request'][k] != request[k] for k in ('id', 'content'))):
            raise ValueError('Reference identity does not match this actual public paper question')
        path = results[history['source_group']]
        record: dict[str, Any] = {'index': index, 'family': history['source_group'],
            'history': history['id'], 'request_id': request['id'],
            'public_question': request['content'],
            'native_question_id': reference['native_control']['native_question_id'],
            'result_path': path, 'execution': 'NOT_EXECUTED_OR_RESULT_UNAVAILABLE',
            'result_status': None, 'answer': None,
            'final_host_input': {'status': 'NO_ACTUAL_RESULT'},
            'actual_final_provider_messages': None, 'material_binding': None,
            'quality_labels': None}
        records.append(record)
        if path is None:
            continue
        result = read_json(Path(path))
        if 'given_retrieval_request' in result or result.get('host_request_generated') is False:
            raise ValueError(
                'Given requests and conditional readouts are not autonomous Host results')
        if (result['bank'] != position_bank(history, request)
                or result['message_id'] != request['id']
                or result['content'] != request['content']):
            raise ValueError('Actual Host result belongs to another bank or public task')
        boundary, messages = final_provider_input(Path(path), result)
        record.update(execution='ACTUAL_RESULT_RETAINED', result_status=result['status'],
            answer=result.get('final_answer'), current_tool_counts=current_tools(result),
            final_host_input=boundary, actual_final_provider_messages=messages,
            material_binding=visible_original_ranges(messages, history['sources'])
                if messages is not None else None)
    return {'status': 'AUTONOMOUS_QASPER_FINAL_INPUT_REVIEW_PACKETS_BOUND_NO_GRADES',
        'planned_families': len(histories), 'records': records,
        'bound_final_inputs': sum(r['actual_final_provider_messages'] is not None for r in records),
        'result_positions': sum(r['result_path'] is not None for r in records),
        'model_calls': 0, 'ledger_recorded': False, 'no_sha_validation': True,
        'scope': 'Actual autonomous Host answers and response-ID-bound provider inputs. '
            'No given-query readout labels reused. Native references remain scoring-only. '
            'Missing/failed inputs remain explicit; original Store presence is never visibility. '
            'Author review must assess full answers, all actual inputs and the fixed source guide.'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('references', type=Path)
    parser.add_argument('results', type=Path,
                        help='JSON family -> actual *-result.json path or null')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    start = time.process_time()
    report = prepare(read_json(args.fixture), read_json(args.references), read_json(args.results))
    report['cpu_seconds_nested'] = time.process_time()-start
    write_json(args.output, report)
    print(report['status'], report['bound_final_inputs'], '/', report['planned_families'])


if __name__ == '__main__':
    main()
