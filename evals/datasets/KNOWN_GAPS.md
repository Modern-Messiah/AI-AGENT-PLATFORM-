# Known retrieval gaps (documented by the CI eval)

Queries that the current stack misses — kept out of the gated dataset on
purpose so the CI signal stays green-meaningful. Each needs a distinct
product improvement, not a threshold tweak:

1. **Pure-synonym paraphrase without a lexical bridge.** — CLOSED by
   query expansion. `как поменять параметры wifi роутера?` scored only
   ~0.34 against a corpus that says «беспроводная сеть» /
   «маршрутизатор». When the primary retrieval is weak, the weak model
   now paraphrases the query with synonyms and the per-variant results
   are RRF-merged (`packages/rag/query_expansion.py`).

2. **Cross-lingual weak-similarity match.** — CLOSED by the same
   expansion path: for mixed-language corpora (chunk metadata.lang) the
   variants include a translation of the question, so
   `почему пустые цитаты в ответе?` retrieves the English runbook via
   its translated variant.

Both closures are verified live (real weak-model calls) but stay OUT of
the keyless CI dataset: CI runs without provider keys, where
LLM-dependent paths deliberately degrade to the original query.
