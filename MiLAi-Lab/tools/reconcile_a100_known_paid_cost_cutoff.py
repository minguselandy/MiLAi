"""Reconcile a closed ledger snapshot with every attributed generic native CPU edge."""
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

root=Path(sys.argv[1]).resolve()
lab=root.parent.parent
read=lambda p:json.loads(Path(p).read_text())
plan=read(root/'external-own-policy-v1/stages-lme-v1/fixed-prefix-prediction451-v1-continuation-007-plan.json')
after_path=Path(plan['budget_before_snapshot']);after=read(after_path)
samples=[]
for folder in ['b-functional8-execution','c-handoff8-execution']:
    for path in (root/folder).glob('arm-*/call-*/runtime/banks/*/*-result.json'):
        result=read(path);samples.append((result['budget_before']['ledger_revision'],path,result['budget_before']))
revision,before_path,before=min(samples,key=lambda row:row[0])
before_named={k:v for k,v in before['compute'].items() if 'a100' in k.lower()}
assert set(before_named)=={'milai_a100_p0_bf16_reload_20261104','milai_a100_p0_bf16_seed0_20261104',
    'milai_a100_p0_float32_reload_20261104','milai_a100_p0_float32_seed0_20261104'}
named={k:v for k,v in after['compute'].items() if 'a100' in k.lower()}
debt_phase='milai_a100_carried_v79_offline_20261104_v1'
assert named[debt_phase]['cpu_seconds']==45.39000000000001
generic={}
for phase,values in after['compute'].items():
    old=before['compute'].get(phase,{})
    change=values.get('cpu_seconds',0)-old.get('cpu_seconds',0)
    if abs(change)>1e-10 and 'a100' not in phase.lower():
        generic[phase]={'before_CPU_seconds':old.get('cpu_seconds',0),'after_CPU_seconds':values.get('cpu_seconds',0),'CPU_difference':change}
assert set(generic)=={'dynamic_memory_laya','dynamic_memory_laya_load'}
paths=[root/'b64-pilot8-owner-v2.json',root/'b64-remaining56-owner-v2.json']
paths += [root/('task-dev64-method-'+name+'-owner.json') for name in ['incumbent-delivery-u16','b0-u33','b1-u33','e3-aggregate-u32']]
paths += [root/'e3-retained-replication'/('e3-aggregate-seed'+str(seed)+'-u32-owner.json') for seed in [1,2]]
paths += [root/'d-update32'/(name+'-owner.json') for name in ['old8-view_cache_incremental','old8-e3-aggregate-u32','new32-view_cache','new32-view_cache_incremental','new32-e3-aggregate-u32']]
paths += [root/'c-repair7-native-v1/owner-v1.json']
paths += [root/'final-confirmation-v1'/name/'learned-owner-v1.json' for name in ['e3-aggregate-u32','e3-aggregate-seed1-u32','e3-aggregate-seed2-u32']]
edges=[]
for path in paths:
    owner=read(path);values=owner['already_recorded_native_CPU']
    assert set(values)<={'dynamic_memory_laya','dynamic_memory_laya_load'}
    edges.append({'source':str(path),'native_CPU_by_phase':values,'generic_native_CPU_seconds':sum(values.values()),
        'cost_boundary':'Already-recorded native CPU nested inside this actual owner child; add only its residual once, never whole+native.'})
kpath=root/'d-controls-v1/known-View/known-View-control-closeout-v1.json'
opath=root/'d-controls-v1/old-output/old-output-control-closeout-v1.json'
cpath=root/'c-handoff8-quality-review.json'
k=read(kpath);o=read(opath)
legacy_progress=read(lab/'data/manifests/a100-development-progress-20261106-v30.json')
for path,cpu in [(kpath,k['native_local_and_load_CPU_seconds_already_paid']),
    (opath,o['native_local_and_load_CPU_seconds_already_paid']),
    (cpath,legacy_progress['cost']['C_native_CPU_already_recorded'])]:
    assert path.is_file();edges.append({'source':str(path),'generic_native_CPU_seconds':cpu,
        'cost_boundary':'Existing aggregated native/load attribution. Never add duplicate per-attempt copies or whole-job CPU again.'})
assert len({row['source'] for row in edges})==20
generic_delta=sum(row['CPU_difference'] for row in generic.values())
attributed=sum(row['generic_native_CPU_seconds'] for row in edges)
assert attributed==generic_delta
named_total=sum(row.get('cpu_seconds',0) for row in named.values())
goal_named=named_total-named[debt_phase]['cpu_seconds']
known_goal=goal_named+generic_delta
generation_delta={key:after['generation'][key]-before['generation'][key] for key in before['generation']}
assert generation_delta['known_tokens']==generation_delta['charged_tokens']==25368797
assert generation_delta['unknown_usage']==0 and after['embedding']==before['embedding']
assert after['generation_requests']-before['generation_requests']==5767
phase_groups={
    'training_profile_fits_and_saved_evaluations':[name for name in named if any(tag in name for tag in ['p0_','a0_seed0','a1_seed0','b0_seed0','b1_seed0','a_saved_','retained_e3_aggregate_seed'])],
    'whole_fixed_query64_models':[name for name in named if name.startswith('milai_a100_reserved64_') and 'whole_child_and_parent' in name],
    'whole_LME_closed_reader_segments':[name for name in named if name.startswith('a100-lme-native451-')],
}
out={'status':'KNOWN_PAID_COST_CUTOFF_EXACT_NAMED_PHASES_PLUS_FULLY_ATTRIBUTED_GENERIC_NATIVE_CPU',
    'timestamp_utc':datetime.now(timezone.utc).isoformat(),'cutoff':'After actualidle36 and all3query64 closures, immediately before LME007 dispatch; not current live ledger.',
    'closed_ledger_snapshot':str(after_path),'earliest_new_functional_budget_source':str(before_path),
    'earliest_functional_ledger_revision':revision,'all32_first_functional_result_budgets_inspected_for_earliest_boundary':True,
    'only_P0_own_phases_preexist_at_generic_baseline':True,'P0_already_paid_own_phases_included_once':True,
    'named_current_goal_phase_count':len(named),'named_phase_CPU_including_carried_debt':named_total,
    'excluded_carried_v79_debt_CPU':named[debt_phase]['cpu_seconds'],'named_new_goal_CPU_seconds':goal_named,
    'generic_CPU_delta_by_phase':generic,'generic_native_CPU_total':generic_delta,
    'all_generic_delta_attribution_edges':edges,'all20_unique_native_edges_sum_exactly_equals_snapshot_delta':True,
    'known_new_goal_CPU_paid_through_cutoff':known_goal,'known_new_goal_CPU_hours':known_goal/3600,
    'known_Host_generation_tokens_since_first_functional_request':generation_delta['known_tokens'],
    'generation_reservation_counter_delta':5767,'request_counter_scope':'Original RunBudget reserve counter; not automatically identical to observed successful HTTP responses or local policy decisions.',
    'new_unknown_generation_usage':0,'legacy_unknown_generation_retained':after['generation']['unknown_usage'],
    'embedding_state_literal_unchanged':True,'legacy_unknown_embedding_retained':after['embedding']['unknown_usage'],
    'limits_equal_across_boundary':before['limits']==after['limits'],
    'all_named_actual_compute_phase_records':named,'selected_measurement_group_phase_references':phase_groups,
    'cost_scope':'Known existing paid measured CPU, with own-named phase amounts plus exactly reconciled native generic differences. Do not add wholechild/raw GNU/native subparts again. Does not include liveLME007/later tasks, post36offline timers, unmetered author/launcher/import/cleanup gaps or lost-parent unknowns. Old-output199.51CPU observed bound is retained, not magically upgraded to full cost. HostGPU0/1 busy hours and currency unmeasured. Historical base model/Source acquisition amortization separate, not new charge.',
    'this_is_not_a_new_operational_ledger':True,'new_charge_or_reset_or_refund':False,
    'new_model_HTTP_calls':0,'original_live_ledger_opened_or_written':False,'no_sha_validation':True,'goal_complete':False}
target=Path(sys.argv[2]).resolve()
with target.open('x') as stream:json.dump(out,stream,ensure_ascii=False,indent=2);stream.write('\n')
print('EXACT_CLOSED_COST_CUTOFF',len(named),'namedphases +20genericedges',generic_delta,
    'knownnewgoalCPU',known_goal,'hours',known_goal/3600,'Hostknown',generation_delta['known_tokens'])
