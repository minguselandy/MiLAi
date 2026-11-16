"""Run one declared Host condition over distinct pre-Host captures with one model cache."""
from __future__ import annotations

import argparse
import os
import site
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def run_batch(
    cases: list[dict[str, Any]], output: Path, budget: Path, *, source_version: str,
    presentation: str = 'current', control_policy: dict[str, Any] | None = None,
    host_enable_thinking: bool | None = None, continue_known_failures: bool = False,
) -> dict[str, Any]:
    """Keep the first outcome for each capture; a known failure may precede a new case."""
    from milai_lab.runners.frozen_host_message import replay_host_message

    names = [case['name'] for case in cases]
    captures = [Path(case['capture']).resolve() for case in cases]
    if (not cases or len(set(names)) != len(names) or len(set(captures)) != len(captures)
            or any(Path(name).name != name or name in {'', '.', '..'} for name in names)):
        raise ValueError('Use distinct captures and unique single-component case names')
    for captured in captures:
        settings = read_json(captured/'before/input-freeze.json')['config']
        if Path(settings['budget_path']).resolve() != budget.resolve():
            raise ValueError('Every Host branch must use the same declared operational ledger')
    output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    driver: dict[str, Any] = {'status':'RUNNING','pid':os.getpid(),
        'planned_positions':len(cases),'completed':[], 'source_version':source_version,
        'presentation':presentation,'control_policy':control_policy,
        'host_enable_thinking':host_enable_thinking,'automatic_retry':False,
        'continue_known_failures':continue_known_failures,
        'scope':'One first full autonomous trajectory per distinct pre-Host capture. '
            'One process and one shared model cache for the declared condition.'}
    write_json(output/'driver.json',driver)
    write_json(output/'cases.json',cases)
    write_json(output/'budget-before.json',read_json(budget))
    models: dict[tuple[Any, ...], Any] = {}
    try:
        for case,captured in zip(cases,captures,strict=True):
            destination = output/case['name']
            driver['active'] = {'name':case['name'],'capture':str(captured),
                                'output':str(destination)}
            write_json(output/'driver.json',driver)
            host = read_json(captured/'host.json')
            result = replay_host_message(captured,destination,presentation,
                source_version=source_version,models=models,control_policy=control_policy,
                host_enable_thinking=host_enable_thinking)
            path = destination/'runtime'/host['host_result_path']
            if read_json(path) != result:
                raise ValueError('Returned Host outcome differs from its persisted first attempt')
            row = {**case,'capture':str(captured),'output':str(destination),
                'result':str(path),'status':result['status'],'answer':result.get('final_answer'),
                'error':result.get('error'),'error_type':result.get('error_type'),
                'error_category':result.get('error_category'),
                'generation_calls':result['generation_calls']}
            driver['completed'].append(row)
            driver['model_cache_entries'] = len(models)
            write_json(output/'driver.json',driver)
            print('CLOSED_HOST_BRANCH',case['name'],result['status'],flush=True)
            known = ((result.get('error_type')=='IncompleteChatResponse'
                      and result.get('error_category')=='provider_protocol')
                     or result.get('error')=='FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED'
                     or (result['status']=='BUDGET_EXHAUSTED'
                         and result.get('error_category')=='budget'
                         and result.get('error_type')=='ValueError'
                         and result.get('error')=='PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED'))
            # A closed per-message cap is an outcome for this distinct capture.
            # Global ledger exhaustion is not included and still stops the batch.
            known = known and all(result['budget_after'][kind]['unknown_usage']
                == result['budget_before'][kind]['unknown_usage']
                for kind in ('generation','embedding'))
            if result['status']!='COMPLETED' and not (continue_known_failures and known):
                raise RuntimeError('First failed Host branch retained; inspect before continuing')
        driver['status'] = ('COMPLETED_WITH_FAILURES' if any(
            row['status']!='COMPLETED' for row in driver['completed']) else 'COMPLETED')
    except BaseException as error:
        driver.update(status='FAILED_RETAINED',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        driver.update(wall_seconds=time.perf_counter()-start,
            cpu_seconds_nested=time.process_time()-cpu,ledger_recorded=False)
        write_json(output/'budget-after.json',read_json(budget))
        write_json(output/'driver.json',driver)
    return driver


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases',type=Path,help='JSON list of unique name/capture records')
    parser.add_argument('output',type=Path)
    parser.add_argument('--budget',type=Path,required=True)
    parser.add_argument('--source-version',required=True)
    parser.add_argument('--presentation',choices=('current','request_adjacent_metadata_v1'),
                        default='current')
    parser.add_argument('--policy-config',type=Path)
    parser.add_argument('--host-enable-thinking',action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument('--continue-known-host-failures',action='store_true')
    parser.add_argument('--host-site-packages',type=Path)
    args = parser.parse_args()
    if args.host_site_packages:
        site.addsitedir(str(args.host_site_packages))
    result = run_batch(read_json(args.cases),args.output,args.budget,
        source_version=args.source_version,presentation=args.presentation,
        control_policy=read_json(args.policy_config) if args.policy_config is not None else None,
        host_enable_thinking=args.host_enable_thinking,
        continue_known_failures=args.continue_known_host_failures)
    print(result['status'],len(result['completed']),flush=True)


if __name__ == '__main__':
    main()
