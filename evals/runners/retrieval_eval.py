"""Quick-and-dirty retrieval eval.

Reads `evals/datasets/sample.jsonl`, runs each query through the live
retriever, computes recall@k and MRR by checking whether expected
substrings appear in any of the returned chunks. Substring-based
oracle is cheap to maintain; replace with id-based ground truth once
the corpus is fixed.

Usage:
    uv run python -m evals.runners.retrieval_eval --tenant demo --k 5 \
        --dataset evals/datasets/ci_retrieval.jsonl --min-recall 0.9
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from packages.rag import retrieve_chunks_with_expansion

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "datasets" / "sample.jsonl"


def _hit_rank(retrieved_contents: list[str], expected_substrings: list[str]) -> int | None:
    for rank, content in enumerate(retrieved_contents, start=1):
        if all(sub.lower() in content.lower() for sub in expected_substrings):
            return rank
    return None


def load_examples(dataset: Path) -> list[dict]:
    return [json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]


async def run(tenant_id: str, k: int, examples: list[dict]) -> float:
    """Returns recall@k over the dataset."""
    hits = 0
    rr_total = 0.0

    for ex in examples:
        results = await retrieve_chunks_with_expansion(query=ex["query"], tenant_id=tenant_id, k=k)
        contents = [r.content for r in results]
        rank = _hit_rank(contents, ex["expected_doc_substrings"])
        if rank is not None:
            hits += 1
            rr_total += 1.0 / rank
            print(f"  ✓ rank={rank}  | {ex['query']}")
        else:
            print(f"  ✗ miss      | {ex['query']}")

    n = len(examples)
    recall = hits / n if n else 0.0
    print(f"\nrecall@{k} = {hits}/{n} = {recall:.2%}")
    print(f"MRR       = {rr_total / n:.3f}" if n else "MRR       = n/a")
    return recall


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default="demo")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p.add_argument(
        "--min-recall",
        type=float,
        default=None,
        help="fail (exit 1) when recall@k falls below this threshold",
    )
    args = p.parse_args()
    recall = asyncio.run(run(args.tenant, args.k, load_examples(args.dataset)))
    if args.min_recall is not None and recall < args.min_recall:
        print(f"FAIL: recall@{args.k} {recall:.2%} is below the required {args.min_recall:.2%}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
