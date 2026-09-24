from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from packages.rag import embedder as embedder_module
from packages.rag.embedder import embed_queries, embed_texts


class _FakeModel:
    def __init__(self) -> None:
        self.passage_calls: list[list[str]] = []
        self.query_calls: list[list[str]] = []

    def passage_embed(self, texts: list[str]) -> Any:
        self.passage_calls.append(list(texts))
        return iter([np.array([0.1, 0.2]) for _ in texts])

    def query_embed(self, texts: list[str]) -> Any:
        self.query_calls.append(list(texts))
        return iter([np.array([0.3, 0.4]) for _ in texts])


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> _FakeModel:
    model = _FakeModel()
    monkeypatch.setattr(embedder_module, "_get_embedder", lambda: model)
    return model


async def test_embed_texts_uses_passage_embedding(fake_model: _FakeModel) -> None:
    result = await embed_texts(["chunk one", "chunk two"])

    assert result == [[0.1, 0.2], [0.1, 0.2]]
    assert fake_model.passage_calls == [["chunk one", "chunk two"]]
    assert fake_model.query_calls == []


async def test_embed_queries_uses_query_embedding(fake_model: _FakeModel) -> None:
    result = await embed_queries(["как настроить ssl?"])

    assert result == [[0.3, 0.4]]
    assert fake_model.query_calls == [["как настроить ssl?"]]
    assert fake_model.passage_calls == []


async def test_empty_inputs_return_empty_without_touching_the_model(
    fake_model: _FakeModel,
) -> None:
    assert await embed_texts([]) == []
    assert await embed_queries([]) == []
    assert fake_model.passage_calls == []
    assert fake_model.query_calls == []
