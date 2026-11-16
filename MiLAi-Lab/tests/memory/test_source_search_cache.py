"""Exact native ranks with current provenance, visibility and literal corpus comparisons."""
import copy

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.retrieval import SourceSearchCache, _lexical_tokens, flat_bm25_rank
from milai_lab.memory.service import MemoryService


@pytest.mark.parametrize('tokenization', ['rawrag_space', 'unicode_v1'])
@pytest.mark.parametrize('texts', [[], ['', '...'],
    ['Café 2042中文检索', 'Cafe\u0301 release 2042', '中文检索结果', 'same', 'same']])
def test_cached_ranks_equal_native_scores_ties_and_empty_cases(tokenization, texts):
    import numpy as np
    from rank_bm25 import BM25Okapi

    units = [{'id': str(i), 'index_text': text} for i, text in enumerate(texts)]
    tokenize = _lexical_tokens if tokenization == 'unicode_v1' else lambda text: text.split(' ')
    tokens = [tokenize(text) for text in texts]
    native = BM25Okapi(tokens) if any(tokens) else None
    cache = SourceSearchCache()
    for query in ['cafe\u0301 中文检索', 'same', 'unmatched', '']:
        for limit in [1, 8]:
            scores = native.get_scores(tokenize(query)) if native else np.zeros(len(units))
            expected = [{**units[int(i)], 'score': float(scores[i])}
                        for i in np.argsort(scores)[::-1][:limit]]
            times = {}
            actual, reused = cache.rank(units, query, limit, scope=('alice',),
                tokenization=tokenization, timings=times)
            assert actual == expected == flat_bm25_rank(units, query, limit,
                                                        tokenization=tokenization)
            assert times['index_seconds'] == 0 if reused else times['index_seconds'] >= 0
    assert cache.builds == 1 and cache.hits == 7


def test_same_ids_with_different_text_and_different_scope_do_not_reuse():
    cache = SourceSearchCache()
    units = [{'id': 'same', 'index_text': 'original zebra'}]
    def rank(rows, scope=('alice',), tokenization='unicode_v1'):
        actual, reused = cache.rank(rows, 'zebra', 8, scope=scope,
                                    tokenization=tokenization, timings={})
        assert actual == flat_bm25_rank(rows, 'zebra', 8, tokenization=tokenization)
        return reused
    assert not rank(units)
    assert rank(copy.deepcopy(units))
    assert not rank([{'id': 'same', 'index_text': 'different zebra'}])
    assert not rank(units)
    assert not rank(units, scope=('bob',))
    assert not rank(units, scope=('bob',), tokenization='rawrag_space')
    assert cache.builds == 5


def test_cache_hit_keeps_the_existing_native_version_requirement(monkeypatch):
    cache = SourceSearchCache()
    units = [{'index_text': 'zebra'}]
    options = {'scope': ('alice',), 'tokenization': 'unicode_v1', 'timings': {}}
    cache.rank(units, 'zebra', 1, **options)
    monkeypatch.setattr('importlib.metadata.version', lambda _: 'changed-runtime')
    with pytest.raises(ValueError, match='RAWRAG_BM25_VERSION_CHANGED'):
        cache.rank(units, 'zebra', 1, **options)


def normalized(result):
    result = copy.deepcopy(result)
    result['source_retrieval'].pop('timings')
    result['source_retrieval'].pop('corpus_index_cache', None)
    return result


def test_current_visibility_order_exclusions_and_new_sources_with_shared_cache(tmp_path):
    cache = SourceSearchCache()
    with SqliteStore.from_conn_string(str(tmp_path/'db')) as store:
        service = MemoryService(store, ('cache', 'alice'), 'alice', tmp_path/'lock',
            functional_contract='functional_v1', source_search_cache=cache)
        original = service.capture_tool('s', 'one', 'observed', 'Zebra approval pending.', None)
        second = service.capture_user('other', 'two', 'Café public report.')
        query = service.capture_user('current', 'q1', 'SECRET_CURRENT_QUERY')
        def compare(**kwargs):
            actual = service.search_sources('zebra CAFÉ', tokenization='unicode_v1', **kwargs)
            service.source_search_cache = None
            expected = service.search_sources('zebra CAFÉ', tokenization='unicode_v1', **kwargs)
            service.source_search_cache = cache
            assert normalized(actual) == normalized(expected)
            return actual
        args = {'excluded_source_refs': [query['source_ref']], 'include_scope': True}
        assert compare(**args)['source_retrieval']['corpus_index_cache'] == 'built'
        assert compare(limit=1, **args)['source_retrieval']['corpus_index_cache'] == 'reused'
        assert cache._entry is not None and 'SECRET_CURRENT_QUERY' not in str(cache._entry.texts)
        # A new excluded current question is not part of the indexed corpus.
        newer = service.capture_user('current', 'q2', 'SECOND_PRIVATE_QUERY')
        args['excluded_source_refs'].append(newer['source_ref'])
        assert compare(**args)['source_retrieval']['corpus_index_cache'] == 'reused'
        prior_builds = cache.builds
        service.capture_tool('s', 'three', 'observed', 'Zebra approval granted.', None)
        compare(**args)
        assert cache.builds == prior_builds + 1
        compare(source_refs=[second['source_ref'], original['source_ref']], **args)
        compare(source_refs=[original['source_ref'], second['source_ref']], **args)
        compare(granularity='turn', **args)
        handle = service.source_fragment_range(original['source_ref'], 0,
                                               len('Zebra approval pending.'))['fragment_handle']
        service.forget('s', 'forget', fragment_handles=[handle])
        result = compare(**args)
        assert original['source_ref'] not in {s['event_id'] for s in result['raw_events']}
        assert 'SECRET_CURRENT_QUERY' not in str(cache._entry.texts)


def test_identical_replacement_text_reuses_only_statistics_not_old_source_binding(tmp_path):
    cache = SourceSearchCache()
    with SqliteStore.from_conn_string(str(tmp_path/'db')) as store:
        service = MemoryService(store, ('cache', 'alice'), 'alice', tmp_path/'lock',
            functional_contract='functional_v1', source_search_cache=cache)
        old = service.capture_user('s', 'old', 'Same exact literal text.')['source_ref']
        first = service.search_sources('literal', tokenization='unicode_v1')
        handle = service.source_fragment_range(old, 0, len('Same exact literal text.'))[
            'fragment_handle']
        service.forget('s', 'forget', fragment_handles=[handle])
        new = service.capture_user('s', 'new', 'Same exact literal text.')['source_ref']
        second = service.search_sources('literal', tokenization='unicode_v1')
        assert second['source_retrieval']['corpus_index_cache'] == 'reused'
        assert [r['event_id'] for r in second['raw_events']] == [new]
        assert old not in str(second['source_materials'])
        assert first['source_materials'][0]['score'] == second['source_materials'][0]['score']
