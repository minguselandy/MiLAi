import copy
import json
from dataclasses import asdict, replace

import pytest
from test_experience_utility import adopt, confirm, revision, session

from milai_lab.analysis.revision_eligibility import assess_revision_reuse, freeze_revision_review
from milai_lab.methods.controlled_workspace import MemoryCard
from milai_lab.methods.experience_utility import VersionUtility, version_key
from milai_lab.methods.reasoning_bank import ExperienceBank


def fixture(*, append=False, regime="H", new_text="narrowed claim", retired=False):
    bank = ExperienceBank(
        {"experiment": "fixture", "domain": "fixture", "split": "DEV", "protocol": "O"},
        {"config": {"embedding_dimension": 2}},
        sources={"source:old": "original", "source:feedback": "visible counterexample"},
    )
    old = MemoryCard("card:1", "original claim", ["source:old"])
    new = MemoryCard(
        "card:2" if append else "card:1",
        new_text,
        ["source:old", "source:feedback"],
        revision=1 if append else 2,
        retired=retired,
    )
    bank.cards = {old.handle: old, new.handle: new} if append else {new.handle: new}
    if not append:
        bank.historical_cards = {"card:1@1": asdict(old)}
    utility = VersionUtility(bank.utility_state)
    utility.register(old)
    utility.finish(
        task_id="formation",
        scope=bank.scope,
        selector_version="fixture",
        feedback_regime=regime,
        sequence=[],
        result_ref="result:formation",
        native_result=True if regime == "R" else None,
        costs={},
        decision_ref="decision:0",
    )
    key = utility.register(
        new,
        predecessor="card:1@1",
        reason="visible counterexample",
        feedback_refs=("source:feedback",),
    )
    actor = {
        "session": "later",
        "role": "actor",
        "status": "SETTLED",
        "request_id": "request:1",
        "payload_sha256": "c" * 64,
        "sequence": 9,
    }
    sequence = []
    utility.confirm(sequence, receipt=actor, versions=[(new.handle, new.revision)], task_id="later")
    utility.finish(
        task_id="later",
        scope=bank.scope,
        selector_version="fixture",
        feedback_regime=regime,
        sequence=sequence,
        result_ref="result:later",
        native_result=None,
        costs={},
        decision_ref="decision:1",
    )
    bank.completed_tasks = ["formation", "later"]
    # Exercise the existing checkpoint/restore contract, not a replacement bank.
    bank = ExperienceBank.restore(bank.checkpoint(), scope=bank.scope, contract=bank.contract)
    review = {
        "revision_id": "revision:1",
        "version_key": key,
        "source_task_id": "formation",
        "created_sequence": 5,
        "review_sequence": 6,
        "policy_version": "fixture",
        "kind": "SCOPE_NARROWING",
        "reason": "scope corrected against visible source",
        "creation_ref": "event:revision",
        "changed_claims": [],
        "changed_applicability": ["exclude unsupported context"],
        "original_evidence_refs": ["source:old"],
        "feedback_visibility": {"source:feedback": "VISIBLE"},
        "support": "SUPPORTED",
        "support_ref": "review:support",
        "feedback_regime": regime,
        "lineage_clusters": ["original", "formation"],
        "provenance_ref": "review:complete-transitive-lineage",
    }
    sealed = freeze_revision_review(bank, review)
    retrieval = {
        "ref": "retrieval:1",
        "task_id": "later",
        "scope_sha256": sealed["scope_sha256"],
        "sequence": 8,
        "version_keys": [key],
    }
    return bank, review, retrieval, actor


def assess(bank, review, retrieval, actor, *, cluster="independent"):
    return assess_revision_reuse(
        bank,
        freeze_revision_review(bank, review),
        later_task_id="later",
        later_cluster=cluster,
        retrieval=retrieval,
        actor_receipt=actor,
    )


@pytest.mark.parametrize("append", [False, True])
def test_existing_replace_and_append_lineages_are_supported_without_mutation(append):
    bank, review, retrieval, actor = fixture(append=append)
    before = copy.deepcopy(bank.checkpoint())
    result = assess(bank, review, retrieval, actor)
    assert result["eligible"] is True
    assert result["observable_use"] == "UNKNOWN"
    assert result["arm_kind"] == "RESEARCH_PROTOTYPE"
    assert result["claim_ceiling"] == "STRUCTURAL_ELIGIBILITY_NOT_BENEFIT"
    assert bank.checkpoint() == before


@pytest.mark.parametrize("kind", ["SCOPE_EXPANSION", "EXAMPLE_REFRESH", "RETIRE", "TYPO"])
def test_non_correction_never_receives_core_credit(kind):
    bank, review, retrieval, actor = fixture()
    review["kind"] = kind
    assert "NOT_CORE_CORRECTION" in assess(bank, review, retrieval, actor)["rejected_reasons"]


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("support", "UNKNOWN", "SEMANTIC_SUPPORT_UNKNOWN"),
        ("support_ref", None, "SEMANTIC_SUPPORT_UNKNOWN"),
        ("changed_applicability", [], "CORRECTION_EVIDENCE_INCOMPLETE"),
        ("lineage_clusters", None, "SOURCE_CLUSTER_INDEPENDENCE_UNKNOWN"),
        ("provenance_ref", None, "SOURCE_CLUSTER_INDEPENDENCE_UNKNOWN"),
        ("feedback_visibility", {"source:feedback": "UNKNOWN"}, "FEEDBACK_VISIBILITY_UNKNOWN"),
    ],
)
def test_absence_is_unknown_not_supported(field, value, reason):
    bank, review, retrieval, actor = fixture()
    review[field] = value
    result = assess(bank, review, retrieval, actor)
    assert result["eligible"] is None
    assert reason in result["unknown_reasons"]


def test_different_task_ids_do_not_establish_source_independence():
    bank, review, retrieval, actor = fixture()
    assert (
        "SHARED_SOURCE_CLUSTER"
        in assess(bank, review, retrieval, actor, cluster="original")["rejected_reasons"]
    )
    assert assess(bank, review, retrieval, actor, cluster=None)["eligible"] is None


def test_hidden_feedback_rejected_under_h_and_r_requires_released_bit():
    bank, review, retrieval, actor = fixture()
    review["feedback_visibility"]["source:feedback"] = "NATIVE_OUTCOME"
    assert (
        "HIDDEN_OUTCOME_NOT_ALLOWED_IN_H"
        in assess(bank, review, retrieval, actor)["rejected_reasons"]
    )
    bank, review, retrieval, actor = fixture(regime="R")
    review["feedback_visibility"]["source:feedback"] = "NATIVE_OUTCOME"
    assert assess(bank, review, retrieval, actor)["eligible"] is True
    bank.utility_state["tasks"]["formation"]["native_result"] = None
    assert assess(bank, review, retrieval, actor)["eligible"] is None


def test_unsupported_correction_and_same_task_reuse_are_ineligible():
    bank, review, retrieval, actor = fixture()
    review["support"] = "UNSUPPORTED"
    assert assess(bank, review, retrieval, actor)["eligible"] is False
    review["support"] = "SUPPORTED"
    review["source_task_id"] = "later"
    assert "SAME_TASK_REUSE" in assess(bank, review, retrieval, actor)["rejected_reasons"]


def test_missing_retrieval_and_wrong_exposed_version_are_not_reuse():
    bank, review, retrieval, actor = fixture()
    retrieval["version_keys"] = []
    assert (
        "REVISED_LINEAGE_NOT_RETRIEVED"
        in assess(bank, review, retrieval, actor)["rejected_reasons"]
    )
    retrieval["version_keys"] = [review["version_key"]]
    bank.utility_state["tasks"]["later"]["exposures"][0]["versions"] = [
        {"memory_ref": "card:1", "revision": 1}
    ]
    assert (
        "REVISED_VERSION_NOT_EXPOSED" in assess(bank, review, retrieval, actor)["rejected_reasons"]
    )


def test_unconfirmed_exposure_is_unknown_and_failed_or_mismatched_receipt_rejected():
    bank, review, retrieval, actor = fixture()
    original = copy.deepcopy(bank.utility_state["tasks"]["later"]["exposures"])
    bank.utility_state["tasks"]["later"]["exposures"] = []
    assert assess(bank, review, retrieval, actor)["eligible"] is None
    bank.utility_state["tasks"]["later"]["exposures"] = original
    with pytest.raises(ValueError, match="CONFIRMED_ACTOR_REQUEST"):
        assess(bank, review, retrieval, {**actor, "status": "FAILED"})
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        assess(bank, review, retrieval, {**actor, "payload_sha256": "d" * 64})


def test_sealed_review_mutation_and_cross_scope_or_early_exposure_fail():
    bank, review, retrieval, actor = fixture()
    sealed = freeze_revision_review(bank, review)
    sealed["review"]["kind"] = "CORRECTION"
    with pytest.raises(ValueError, match="FROZEN_REVISION_REVIEW_CHANGED"):
        assess_revision_reuse(
            bank,
            sealed,
            later_task_id="later",
            later_cluster="independent",
            retrieval=retrieval,
            actor_receipt=actor,
        )
    with pytest.raises(ValueError, match="RETRIEVAL_BINDING_MISMATCH"):
        assess(bank, review, {**retrieval, "scope_sha256": "wrong"}, actor)
    with pytest.raises(ValueError, match="CHRONOLOGY_MISMATCH"):
        assess(bank, review, retrieval, {**actor, "sequence": 6})


def test_historical_revised_version_keeps_valid_past_exposure_after_later_revision():
    bank, review, retrieval, actor = fixture()
    old = bank.cards["card:1"]
    bank.historical_cards[version_key(old.handle, old.revision)] = asdict(old)
    newer = replace(old, revision=3, text="another later change")
    bank.cards["card:1"] = newer
    VersionUtility(bank.utility_state).register(newer, predecessor="card:1@2")
    assert assess(bank, review, retrieval, actor)["eligible"] is True


def test_exact_card_content_is_checked_by_existing_utility_validator():
    bank, review, retrieval, actor = fixture()
    bank.cards["card:1"].text = "tampered"
    with pytest.raises(ValueError, match="UTILITY_VERSION_CONTENT_CHANGED"):
        assess(bank, review, retrieval, actor)


@pytest.mark.parametrize("change", ["source", "contract", "release"])
def test_frozen_review_binds_evidence_contents_contract_and_feedback_release(change):
    bank, review, retrieval, actor = fixture(regime="R")
    sealed = freeze_revision_review(bank, review)
    if change == "source":
        bank.sources["source:old"] = "different original evidence under the same ref"
    elif change == "contract":
        bank.contract["changed_policy"] = True
    else:
        bank.utility_state["tasks"]["formation"]["native_result"] = False
    with pytest.raises(ValueError, match="FROZEN_REVISION_REVIEW_CHANGED"):
        assess_revision_reuse(
            bank,
            sealed,
            later_task_id="later",
            later_cluster="independent",
            retrieval=retrieval,
            actor_receipt=actor,
        )


def test_original_formation_is_not_a_revision_and_lineage_cycles_fail():
    bank, review, _retrieval, _actor = fixture()
    with pytest.raises(ValueError, match="EXISTING_REVISION_LINEAGE"):
        freeze_revision_review(bank, {**review, "version_key": "card:1@1"})
    bank.utility_state["versions"]["card:1@1"]["predecessor"] = "card:1@2"
    with pytest.raises(ValueError, match="LINEAGE_CYCLE"):
        freeze_revision_review(bank, review)


def test_correction_needs_a_changed_claim_and_unsupported_review_does_not_count():
    bank, review, retrieval, actor = fixture()
    review.update(kind="CORRECTION", changed_claims=["corrected claim"], changed_applicability=[])
    assert assess(bank, review, retrieval, actor)["eligible"] is True
    review["support"] = "UNSUPPORTED"
    assert "UNSUPPORTED_CORRECTION" in assess(bank, review, retrieval, actor)["rejected_reasons"]


def test_evidence_cannot_be_omitted_or_feedback_invented():
    bank, review, _retrieval, _actor = fixture()
    with pytest.raises(ValueError, match="ORIGINAL_EVIDENCE_MISMATCH"):
        freeze_revision_review(bank, {**review, "original_evidence_refs": []})
    with pytest.raises(ValueError, match="FEEDBACK_BINDING_MISMATCH"):
        freeze_revision_review(bank, {**review, "feedback_visibility": {}})


@pytest.mark.parametrize("versions", ["card:1@20", [None], ["card:1@2", "card:1@2"]])
def test_retrieval_requires_exact_version_list_not_substring_membership(versions):
    bank, review, retrieval, actor = fixture()
    with pytest.raises(ValueError, match="INVALID_LATER_RETRIEVAL"):
        assess(bank, review, {**retrieval, "version_keys": versions}, actor)


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"new_text": "original claim"}, "NO_CLAIM_TEXT_CHANGE"),
        ({"retired": True}, "REVISED_VERSION_RETIRED"),
    ],
)
def test_metadata_only_change_and_retired_version_are_not_correction_reuse(options, reason):
    bank, review, retrieval, actor = fixture(**options)
    result = assess(bank, review, retrieval, actor)
    assert result["eligible"] is False
    assert reason in result["rejected_reasons"]


def test_existing_session_revision_restore_and_later_exposure_join_without_model_calls():
    value, _calls = session(
        [adopt("card:1"), "success", json.dumps({"new_memory": "", "revision": revision()})]
    )
    value.start("formation", "synthetic current task")
    confirm(value)
    assert value.observe("tool", "synthetic visible counterexample") == "source:3"
    value.seal_result("result:formation")
    value.finish("synthetic visible work", commit=True)
    bank = ExperienceBank.restore(
        value.checkpoint(), scope=value.bank.scope, contract=value.bank.contract
    )
    _, review, retrieval, _ = fixture()
    review.update(original_evidence_refs=["source:1"], feedback_visibility={"source:3": "VISIBLE"})
    # Actually seal before the later mock session, not after inspecting its outcome.
    sealed = freeze_revision_review(bank, review)
    retrieval["scope_sha256"] = sealed["scope_sha256"]
    later, _calls = session([adopt("card:1"), "fail", '{"new_memory":""}'], bank=bank)
    later.start("later", "independent synthetic task")
    _messages, actor = confirm(later)
    later.seal_result("result:later")
    later.finish("synthetic later work", commit=True)
    result = assess_revision_reuse(
        bank,
        sealed,
        later_task_id="later",
        later_cluster="independent",
        retrieval=retrieval,
        actor_receipt={**actor, "sequence": 9},
    )
    assert result["eligible"] is True
    assert result["observable_use"] == "UNKNOWN"
