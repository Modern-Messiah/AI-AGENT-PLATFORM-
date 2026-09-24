# Known retrieval gaps (documented by the CI eval)

Queries that the current stack misses — kept out of the gated dataset on
purpose so the CI signal stays green-meaningful. Each needs a distinct
product improvement, not a threshold tweak:

1. **Pure-synonym paraphrase without a lexical bridge.**
   `как поменять параметры wifi роутера?` — the corpus says
   «беспроводная сеть» / «маршрутизатор». No shared tokens, semantic
   similarity of the best (correct) chunk is only ~0.34, far below any
   sane unsupported-query gate. Fix direction: query expansion /
   synonym normalization before retrieval.

2. **Cross-lingual weak-similarity match.**
   `почему пустые цитаты в ответе?` against an English runbook chunk
   ("Empty citations mean…") — best score ~0.19. Dropping the gate this
   low would let garbage through on real corpora. Fix direction:
   cross-lingual query translation for corpora detected as mixed-language
   (chunk metadata.lang already exists).
