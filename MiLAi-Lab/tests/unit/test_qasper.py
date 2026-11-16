"""Native paper grouping and label-free public Source/Host inputs."""
import copy
import json
import sys
import tarfile
from io import BytesIO

import pytest

from milai_lab.datasets.qasper import QUESTION_PROMPT_PREFIX, allocate_papers, export_paper
from prepare_qasper_sources import main


def paper():
    return {"title": "A study", "abstract": "An abstract.",
        "full_text": [{"section_name": "Methods", "paragraphs": ["Shared paragraph."]},
                      {"section_name": "Results", "paragraphs": [
                          "Shared paragraph.", "Complementary result.", "Unmarked paragraph."]}],
        "figures_and_tables": [{"caption": "A plot caption.", "file": "plot.png"}],
        "qas": [{"question": "What is supported?", "question_id": "native-question",
                 "answers": [{"annotation_id": "annotation-1", "answer": {
                    "unanswerable": False, "extractive_spans": [], "yes_no": None,
                    "free_form_answer": "PRIVATE GOLD", "evidence": [
                        "Shared paragraph.", "Complementary result.", "Missing paragraph.",
                        "FLOAT SELECTED: plot.png"], "highlighted_evidence": []}}]},
                {"question": "What cannot be established?", "question_id": "native-unanswerable",
                 "answers": [{"annotation_id": "annotation-2", "answer": {
                    "unanswerable": True, "extractive_spans": [], "yes_no": None,
                    "free_form_answer": "", "evidence": [], "highlighted_evidence": []}}]}]}


def test_native_paper_allocation_keeps_all_questions_in_one_partition_without_labels():
    train = {str(i): paper() for i in range(5)}
    dev = {"dev-" + str(i): paper() for i in range(4)}
    allocation = allocate_papers(train, dev, train_count=3, dev_count=2, seed=0)
    assert sum(g["split"] == "train" for g in allocation) == 3
    assert sum(g["split"] == "dev" for g in allocation) == 2
    assert sum(g["split"] == "unused" for g in allocation) == 4
    assert all(g["split"] in (g["native_split"], "unused") for g in allocation)
    changed = {key: {"unrelated": "no annotation-based allocation"} for key in train}
    assert allocate_papers(changed, dev, train_count=3, dev_count=2, seed=0) == allocation
    with pytest.raises(ValueError, match="both train and dev"):
        allocate_papers(train, train, train_count=1, dev_count=1, seed=0)


def test_all_literal_sources_are_public_and_annotations_cannot_change_requests():
    native = paper()
    public, controls = export_paper("paper-id", native, "train")
    assert len(public["sources"]) == 8 and len(public["requests"]) == 2
    assert "PRIVATE GOLD" not in json.dumps(public)
    assert "native-question" not in json.dumps(public)
    assert "Unmarked paragraph." in json.dumps(public)
    changed = copy.deepcopy(native)
    for qa in changed["qas"]:
        qa["answers"] = []
    assert export_paper("paper-id", changed, "train")[0] == public
    assert controls[0]["annotations"][0]["answer"]["free_form_answer"] == "PRIVATE GOLD"


def test_explicit_given_query_preserves_native_question_and_is_independent_of_labels():
    native = paper()
    native['qas'][0]['question'] = '  WhIch “models”\nwere compard?  '
    autonomous, controls = export_paper('paper-id', native, 'train')
    supplied, supplied_controls = export_paper('paper-id', native, 'train', given_requests=True)
    assert supplied_controls == controls
    assert supplied['sources'] == autonomous['sources']
    for actual, original, qa in zip(supplied['requests'], autonomous['requests'], native['qas'],
                                    strict=True):
        assert actual['content'] == original['content'] == QUESTION_PROMPT_PREFIX + qa['question']
        assert actual['retrieval_request']['query'] == qa['question']
        assert {k: v for k, v in actual.items() if k != 'retrieval_request'} == original
    changed = copy.deepcopy(native)
    for qa in changed['qas']:
        qa['answers'] = []
        qa['question_id'] = 'different-hidden-id'
    assert export_paper('paper-id', changed, 'train', given_requests=True)[0] == supplied
    assert 'PRIVATE GOLD' not in json.dumps(supplied)
    assert all('retrieval_request' not in r for r in autonomous['requests'])


def test_duplicate_text_locations_remain_alternatives_and_unmatched_is_not_negative():
    _, controls = export_paper("paper-id", paper(), "dev")
    evidence = controls[0]["annotations"][0]["evidence"]
    assert evidence[0]["source_event_ids"] == ["paper-id/section-0-paragraph-0",
                                              "paper-id/section-1-paragraph-0"]
    assert [e["status"] for e in evidence] == [
        "matched_text", "matched_text", "unmatched_text", "non_text_evidence"]
    assert evidence[-1]["source_event_ids"] == []  # Caption alone is not the actual plot.
    assert controls[1]["annotations"][0]["answer"]["unanswerable"]
    assert all(c["operation_labels"] == [] for c in controls)


def test_multiple_answer_annotations_are_not_merged_into_one_required_evidence_set():
    native = paper()
    alternate = copy.deepcopy(native["qas"][0]["answers"][0])
    alternate["annotation_id"] = "alternate"
    alternate["answer"]["evidence"] = ["Unmarked paragraph."]
    native["qas"][0]["answers"].append(alternate)
    _, controls = export_paper("paper-id", native, "train", max_questions=1)
    assert len(controls) == 1
    assert [len(a["evidence"]) for a in controls[0]["annotations"]] == [4, 1]


def test_native_untitled_section_keeps_original_paragraph_without_invented_title():
    native = paper()
    native["full_text"][0]["section_name"] = None
    public, controls = export_paper("paper-id", native, "train")
    source = next(s for s in public["sources"] if s["event_key"] == "section-0-paragraph-0")
    assert source["content"] == "A study\nShared paragraph."
    assert "paper-id/section-0-paragraph-0" in controls[0]["annotations"][0][
        "evidence"][0]["source_event_ids"]


def test_official_header_and_newline_mapping_does_not_rewrite_source_or_fuzzily_match():
    native = paper()
    native["full_text"][0]["paragraphs"] = ["  Literal\nparagraph.  "]
    native["qas"][0]["answers"][0]["answer"]["evidence"] = [
        "Methods", "Literal paragraph.", "Literal  paragraph."]
    public, controls = export_paper("paper-id", native, "train")
    evidence = controls[0]["annotations"][0]["evidence"]
    assert evidence[0]["source_event_ids"] == ["paper-id/section-0-heading"]
    assert evidence[1]["match_basis"] == "native_newline_strip"
    assert evidence[2]["status"] == "unmatched_text"
    assert any(s["content"].endswith("  Literal\nparagraph.  ") for s in public["sources"])


@pytest.mark.parametrize('given', [False, True])
def test_native_archive_cli_exports_existing_fixture_shape_and_separate_controls(tmp_path,
                                                                              monkeypatch, given):
    path = tmp_path / "qasper.tgz"
    with tarfile.open(path, "w:gz") as archive:
        for split in ("train", "dev"):
            body = json.dumps({split + "-paper": paper()}).encode()
            member = tarfile.TarInfo(f"qasper-{split}-v0.3.json")
            member.size = len(body)
            archive.addfile(member, BytesIO(body))
    output = tmp_path / "prepared"
    monkeypatch.setattr(sys, "argv", ["prepare_qasper_sources", str(path), str(output),
        "--train-papers", "1", "--dev-papers", "1", *(['--given-requests'] if given else [])])
    main()
    public = json.loads((output / "train.json").read_text())
    assert set(public) == {"histories"}
    assert public["histories"][0]["split"] == "train"
    assert "PRIVATE GOLD" not in json.dumps(public)
    report = json.loads((output / "preparation.json").read_text())
    assert report["splits"]["train"]["papers"] == 1
    assert report["splits"]["train"]["questions"] == 2
    assert report["model_calls"] == report["operation_labels"] == 0
    assert report['given_requests'] == given
    request = public['histories'][0]['requests'][0]
    assert ('retrieval_request' in request) == given
    if given:
        assert request['retrieval_request']['query'] == 'What is supported?'


def test_native_paper_id_runs_as_a_real_store_bank_without_renaming_the_source(tmp_path):
    from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore
    from milai_lab.memory.service import MemoryService

    public, controls = export_paper("1909.05246", paper(), "train")
    with TransactionalSqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("qasper", public["id"], "owner"), "owner",
                                tmp_path / "lock", functional_contract="functional_v1")
        source = public["sources"][0]
        receipt = service.capture_tool(source["session_id"], source["event_key"], source["origin"],
                                       source["content"], None, occurred_at=source["occurred_at"])
        assert receipt["ok"]
        assert service.source(receipt["source_ref"])["content"] == source["content"]
    assert public["source_group"] == "qasper-paper-1909.05246"
    assert controls[0]["paper_id"] == "1909.05246"
    # Literal percent text is distinct from an escaped period, without a content fingerprint.
    other, _ = export_paper("1909%2E05246", paper(), "train")
    assert other["id"] != public["id"]
