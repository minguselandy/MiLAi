"""Network-denied SDK probes with pinned production template; no natural model samples."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.functional_state import canonical
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners import functional

LAB = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=False)
    baseline = read_json(LAB / 'configs/v13-5-functional-r52.json')
    capacity = HostCapacity(baseline['capacity'])
    sys.path.insert(0, str(LAB))
    from tests.memory import test_v13_5_functional as memory_probes
    from tests.unit import test_v13_5_functional_integration as probes

    actual_prepare = functional.prepare

    def production_template_prepare(root: Path, path: Path, **kwargs: Any) -> Any:
        settings = read_json(path)
        settings['host'].update({k: v for k, v in baseline['host'].items() if k != 'base_url'})
        settings['capacity'] = baseline['capacity']
        settings['system_prompt'] = baseline['system_prompt']
        settings['declaration_thinking'] = baseline['declaration_thinking']
        settings['declaration_sampling'] = baseline['declaration_sampling']
        settings['http_ownership_domain']['clients'] = [settings['host']]
        write_json(path, settings)
        return actual_prepare(root, path, **kwargs)

    def forbid(*unused: Any, **unused_kwargs: Any) -> Any:
        raise AssertionError('POST_R52_MECHANICAL_NETWORK_FORBIDDEN')

    cases = [probes.test_support_working_view_uses_actual_agent_read_then_save,
             probes.test_bounded_reproposal_actual_agent_stops_before_third_review]
    rows = []
    for case in cases:
        root = args.root / case.__name__
        root.mkdir()
        with pytest.MonkeyPatch.context() as patch:
            for name in ('connect', 'connect_ex'):
                patch.setattr(socket.socket, name, forbid)
            for name in ('create_connection', 'getaddrinfo'):
                patch.setattr(socket, name, forbid)
            patch.setattr(functional, 'prepare', production_template_prepare)
            case(root, patch)
        requests = []
        for path in root.glob('run/banks/*/*-trace-*.jsonl'):
            for line in path.read_text().splitlines():
                event = json.loads(line)
                if event.get('event') != 'vllm_response':
                    continue
                wire = event['request']
                thinking = wire.get('chat_template_kwargs', {}).get('enable_thinking', True)
                counter = HostCapacity({**baseline['capacity'], 'enable_thinking': thinking})
                receipt = counter.check(wire['messages'], wire['max_tokens'], wire.get('tools'))
                requests.append({'capacity': receipt, 'thinking': thinking,
                                 'tool_choice': wire.get('tool_choice'),
                                 'temperature': wire['temperature']})
        assert requests
        rows.append({'probe': case.__name__, 'status': 'PASS_SCRIPTED', 'requests': requests})
    root = args.root / 'oversized_metadata'
    root.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, 'connect', forbid)
        memory_probes.check_oversized_metadata_progress(root, capacity.text_tokens)
    root = args.root / 'support_view_oversized_scope'
    root.mkdir()
    with memory_probes.opened(root, support_context=True, read_interface='explicit_selectors_v1',
                             material_limit=8192) as memory:
        memory.token_count = capacity.text_tokens
        ref = memory_probes.turn(memory, text='Proposed three visits weekly; start date unknown.')
        selected = memory_probes.handles(memory, ref)
        saved = memory.save(cast(RunnableConfig, memory_probes.cfg()), 'save',
                            'Proposed three visits weekly.', selected,
                            scope={'condition': 'public condition 0123456789 ' * 12000})
        before = memory.service.read(saved['id'])
        page = memory_probes.invoke(memory, 'read_support_context', {
            'read_handle': before['candidate_handle'], 'fragment_handles': selected}, 'view')
        assert page['skipped_units'][0]['type'] == 'record'
        assert page['items'][0]['content'].endswith('start date unknown.')
        assert page['next_cursor'] is None and page['examined_units'] == 2
        packet_tokens = capacity.text_tokens(canonical(page))
        assert packet_tokens <= 8192 and memory.service.read(saved['id']) == before
    report = {'schema': 'post_r52_production_template_mechanical_v1', 'status': 'PASS',
              'actual_model_http': 0, 'actual_embedding_http': 0,
              'production_tokenizer': capacity.identity, 'scripted_probes': rows,
              'oversized_metadata_progress': 'PASS', 'support_view_packet_tokens': packet_tokens,
              'limit': 'Synthetic scripted transport; no natural-model semantic evidence.'}
    write_json(args.root / 'report.json', report)
    print(json.dumps({k: report[k] for k in ('status', 'actual_model_http',
                     'oversized_metadata_progress', 'support_view_packet_tokens')}))


if __name__ == '__main__':
    main()
