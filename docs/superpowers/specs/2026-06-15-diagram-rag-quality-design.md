# Diagram RAG Quality Design

## Problem

Visual ingestion extracts the incident-bot diagrams correctly, but retrieval loses
the useful description before the LLM sees it:

- Russian diagram queries are ranked with an English-only embedding model.
- Exact diagram titles do not receive an explicit lexical boost.
- A diagram description may be split so the title and its flow logic land in
  different chunks.
- Context assembly consumes the budget greedily, so later selected citations can
  disappear from the prompt entirely.
- Vision runs on text-heavy PDF pages and adds verbose formatting descriptions
  that compete with useful content.

## Design

### Retrieval

Keep pgvector cosine search as the candidate generator, then rerank candidates in
Python with a deterministic lexical score. Tokenization is Unicode-aware and
normalizes case. Exact phrase and uncommon query-term overlap receive a bounded
boost, while semantic score remains the primary signal.

For scoped document chat, retrieve a wider candidate set before reranking. This
is cheap because the query is restricted to one document and avoids losing a
diagram chunk that ranks just below the initial vector cutoff.

### Embeddings

Change the default embedding model to
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. It is supported by
FastEmbed and keeps the existing 384-dimensional database column.

Existing documents must be reindexed after the model changes. The application
will expose the configured embedding model in chunk metadata, allowing retrieval
to ignore incompatible stale vectors instead of silently mixing models.

### Visual Chunking

Visual page analysis remains one page-level segment, but diagram sections headed
by Markdown headings such as `### Schema 2` are split into self-contained logical
segments before the generic character splitter runs. The heading is retained
with its section body.

### Context Budget

Context assembly reserves a fair per-citation budget before distributing unused
space. Every selected citation receives a header and a useful excerpt whenever
the total budget can hold all headers. No selected source may disappear silently.

### Vision Selection

Text-only pages with a substantial PDF text layer skip Vision. Pages containing
embedded images or drawings still use Vision. The prompt asks for process
semantics: nodes, conditions, directed transitions, loops, and table relations,
and explicitly avoids describing colors and typography unless meaningful.

## Verification

The incident-bot PDF is reindexed and must answer:

1. The B2C and B2B branches in payment verification.
2. The exact flow after router reboot does not help.
3. The external systems connected to Bot Backend.

Each answer must cite the relevant page, and the second answer must include page
4 rather than claim the information is absent.

