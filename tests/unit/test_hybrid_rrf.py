from __future__ import annotations

from packages.rag.retriever import rrf_merge


def test_rrf_merge_prefers_hits_from_both_lists() -> None:
    vector_ids = ["a", "b", "c"]
    fts_ids = ["b", "d", "e"]

    merged = rrf_merge(vector_ids, fts_ids)

    # "b" appears in both lists -> highest fused score, first overall.
    assert merged[0] == "b"
    # Everything is present exactly once.
    assert sorted(merged) == ["a", "b", "c", "d", "e"]


def test_rrf_merge_uses_rank_positions_not_scores() -> None:
    # Rank 1 in a single list beats rank 3 of the other list.
    merged = rrf_merge(["x", "y", "z"], ["q"])

    # x (rank 0) and q (rank 0) both get 1/(60+1); ties broken by id.
    assert merged[0:2] == ["q", "x"] or merged[0:2] == ["x", "q"]
    assert merged[-1] == "z"


def test_rrf_merge_empty_inputs() -> None:
    assert rrf_merge([], []) == []
    assert rrf_merge(["a"], []) == ["a"]
    assert rrf_merge([], ["a"]) == ["a"]


def test_rrf_merge_limit_caps_the_pool() -> None:
    merged = rrf_merge(["a", "b", "c"], ["c", "d", "e"], limit=3)

    assert len(merged) == 3
    assert merged[0] == "c"  # present in both lists


def test_rrf_merge_exact_term_missed_by_vector_is_reachable() -> None:
    # The scenario hybrid search exists for: the FTS leg found a chunk the
    # vector leg never returned — it must survive the fusion.
    merged = rrf_merge(["v1", "v2", "v3"], ["fts-only"])

    assert "fts-only" in merged
