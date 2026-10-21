"""Real Store integration; the optional reviewed upstream core is supplied explicitly."""
import json
import os

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.baselines.coalent_store import SourceRetriever, StoreCognitionStore
from milai_lab.memory.service import MemoryService


@pytest.fixture
def coalent(monkeypatch):
    path = os.environ.get("MILAI_COALENT_RESEARCH_PATH")
    if path is None:
        pytest.skip("Set MILAI_COALENT_RESEARCH_PATH to the reviewed native-version core")
    monkeypatch.syspath_prepend(path)
    import coalent

    return coalent


def service_at(store, tmp_path, owner="alice"):
    return MemoryService(store, ("coalent-port-test", owner), owner, tmp_path / (owner + ".lock"),
                         functional_contract="functional_v1")


def make_cache(coalent, service, search, events, synth_calls):
    def embed(text):
        words = {"alpha", "beta"}
        return [float(word in text.lower()) for word in sorted(words)]

    class Synthesizer:
        def synthesize(self, query, chunks):
            synth_calls.append([c.artifact_id for c in chunks])
            return coalent.Synthesis({"summary": "", "claims": [
                json.loads(c.text)["content"] for c in chunks]}, used=list(range(len(chunks))))

    persistence = StoreCognitionStore(service)
    cache = coalent.SemanticCache(SourceRetriever(service, search, events.append), Synthesizer(),
        embedder=coalent.FunctionEmbedder(embed), store=persistence,
        pool_header=lambda unit: "[sources " + ",".join(unit.provenance.artifact_ids()) + "]")
    return cache, persistence


def test_source_port_keeps_roles_clocks_and_exact_search_scope(tmp_path, coalent):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        user = service.capture_user("history", "1", "alpha report", occurred_at="2035-01-02",
                                    calendar_context="reported local day")[
            "source_ref"]
        assistant = service.capture_assistant("history", "2", "alpha inference")["source_ref"]
        tool = service.capture_tool("history", "tool-1", "lookup",
                                    '{"status":"ok","value":7}', None)["source_ref"]
        unselected = service.capture_user("history", "3", "beta report")["source_ref"]
        bob = service_at(store, tmp_path, "bob")
        other = bob.capture_user("history", "1", "alpha other owner")["source_ref"]
        events, calls = [], []
        def search(query, namespace):
            calls.append((query, namespace))
            return [assistant, tool, user, assistant, other]
        result = SourceRetriever(service, search, events.append).retrieve("alpha", namespace="n")
        assert [c.artifact_id for c in result] == [assistant, tool, user]
        assert all(c.version == "1" and not c.content_hash for c in result)
        assert [json.loads(c.text)["role"] for c in result] == ["assistant", "tool", "user"]
        assert [json.loads(c.text)["reported_at"] for c in result] == [None, None, "2035-01-02"]
        assert json.loads(result[2].text)["captured_at"] == service.source(user)["observed_at"]
        assert json.loads(result[1].text)["origin"] == "lookup"
        assert json.loads(result[1].text)["content"] == '{"status":"ok","value":7}'
        assert json.loads(result[2].text)["calendar_context"] == "reported local day"
        assert events[0]["unavailable_source_refs"] == [other]
        assert unselected not in events[0]["requested_source_refs"] and calls == [("alpha", "n")]


def test_cache_survives_real_store_reopen_and_forget_invalidates(tmp_path, coalent):
    database = str(tmp_path / "bank.sqlite")
    events, synth_calls, search_calls = [], [], []
    with SqliteStore.from_conn_string(database) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("history", "1", "alpha report")["source_ref"]
        def search(query, namespace):
            search_calls.append(query)
            return [ref]
        cache, persistence = make_cache(coalent, service, search, events, synth_calls)
        assert "alpha report" in json.dumps(cache.get("alpha").context)
        assert len(persistence) == 1
        unit_id = persistence.all()[0].id
        assert persistence.get(unit_id).provenance.source_spans[0].artifact_id == ref
    with SqliteStore.from_conn_string(database) as store:
        service = service_at(store, tmp_path)
        cache, persistence = make_cache(coalent, service, search, events, synth_calls)
        sync = persistence.sync_sources(cache)
        assert not sync["changes"][0]["invalidation"]["dirtied"]
        assert "alpha report" in json.dumps(cache.get("alpha").context)
        assert len(search_calls) == len(synth_calls) == 1
        fragment = service.source_fragment_range(ref, 0, len("alpha report"))["fragment_handle"]
        service.forget("history", "forget-alpha", fragment_handles=[fragment])
        sync = persistence.sync_sources(cache)
        assert sync["changes"][0]["invalidation"]["deleted"]
        assert len(persistence) == 0
        assert "alpha report" not in json.dumps(cache.get("alpha").context)
        assert events[-1]["unavailable_source_refs"] == [ref]


def test_new_unbound_source_is_retrievable_without_global_invalidation(tmp_path, coalent):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        alpha = service.capture_user("history", "1", "alpha report")["source_ref"]
        refs = {"alpha": alpha}
        cache, persistence = make_cache(coalent, service,
            lambda query, namespace: [refs[query]], [], [])
        cache.get("alpha")
        beta = service.capture_user("history", "2", "beta report")["source_ref"]
        refs["beta"] = beta
        sync = persistence.sync_sources(cache)
        assert sync["bound_sources_enumerated"] == 1
        assert not sync["changes"][0]["invalidation"]["dirtied"]
        result = cache.get("beta")
        assert beta in result.sources and "beta report" in json.dumps(result.context)
        assert len(persistence) == 2


def test_store_pages_and_owner_namespaces_are_separate(tmp_path, coalent):
    from coalent.domain.models import ProvenanceManifest
    from coalent.semantic.unit import Cognition

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        alice, bob = service_at(store, tmp_path), service_at(store, tmp_path, "bob")
        a, b = StoreCognitionStore(alice), StoreCognitionStore(bob)
        for index in range(513):
            a.put(Cognition(id=str(index), namespace="n", query="alpha", query_embedding=(1., 0.),
                            understanding={}, evidence=(), provenance=ProvenanceManifest("m", "p")))
        assert len(a.all()) == 513 and len(b) == 0 and b.get("0") is None
        a.delete("0")
        assert len(a) == 512 and a.get("0") is None


@pytest.mark.parametrize("content,ok", [
    ('{"claims":["alpha report"],"used":[0]}', True), ("not JSON", False)])
def test_upstream_synthesizer_uses_metered_wire_without_retry(tmp_path, coalent, content, ok):
    import httpx
    from coalent.semantic.synthesizer import LLMSynthesizer

    from milai_lab.baselines.coalent_providers import CoalentGenerationProvider
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

    requests, admissions, events = [], [], []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "existing-model", "choices": [{
            "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}})
    budget = RunBudget(RunLimits(), tmp_path / "mock-budget.json")
    with VLLMClient(VLLMConfig(base_url="http://fixture/v1", model="existing-model",
                              enable_thinking=False), budget=budget,
                    transport=httpx.MockTransport(respond)) as client:
        provider = CoalentGenerationProvider(client, admit=lambda: admissions.append(1),
                                             record=events.append)
        synth = LLMSynthesizer(provider, model="existing-model", max_tokens=37,
                              temperature=.2, retries=0)
        result = synth.synthesize(
            "alpha?", [coalent.Chunk("source-a", "alpha report", version="1")])
    assert result.ok is ok and len(requests) == len(admissions) == len(events) == 1
    assert requests[0]["max_tokens"] == 37 and requests[0]["temperature"] == .2
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "EXTRACT every atomic fact" in requests[0]["messages"][1]["content"]
    assert "[S0] (source-a)\nalpha report" in requests[0]["messages"][1]["content"]
    assert result.usage.total_tokens == budget.state["generation"]["known_tokens"] == 18
    assert budget.state["generation_requests"] == 1
    if not ok:
        assert result.understanding == {"_synthesis_failed": True} and result.used == []


def test_embedding_port_uses_existing_capacity_batching_and_meter(tmp_path, coalent):
    import httpx
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    from milai_lab.baselines.coalent_providers import CoalentEmbedder
    from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
    from milai_lab.providers.embedding_capacity import MeteredEmbeddings

    tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "alpha": 1, "beta": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        vectors = {"alpha": [2., 0.], "beta": [0., 3.]}
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": vectors[text]}
            for i, text in reversed(list(enumerate(body["input"])))],
            "usage": {"prompt_tokens": len(body["input"]), "total_tokens": len(body["input"])}})
    budget = RunBudget(RunLimits(), tmp_path / "mock-budget.json")
    with VLLMClient(VLLMConfig(base_url="http://fixture/v1", model="existing-embedder"),
                    budget=budget, transport=httpx.MockTransport(respond)) as client:
        embeddings = MeteredEmbeddings(client, "existing-embedder", dimension=2, batch_size=8,
            config={"tokenizer_path": str(path), "context_tokens": 32})
        port = CoalentEmbedder(embeddings)
        assert port.embed("alpha") == [1., 0.]
        assert port.embed_many(["beta", "alpha"]) == [[0., 1.], [1., 0.]]
    assert [r["input"] for r in requests] == [["alpha"], ["beta", "alpha"]]
    assert budget.state["embedding"]["known_tokens"] == 3
    assert budget.state["generation_requests"] == 0
