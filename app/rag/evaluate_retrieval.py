"""Score the retrieval step with tests/eval_set.json and help you choose min_vector_score.

    docker compose exec api python -m app.rag.evaluate_retrieval
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app.config import settings
from app.rag.retriever import HybridRetriever


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p * (len(ordered) - 1))))
    return ordered[index]


def main() -> None:
    items = json.loads(Path("tests/eval_set.json").read_text(encoding="utf-8"))
    retriever = HybridRetriever()
    if not retriever.is_ready():
        raise SystemExit("The knowledge base is empty. Run: python -m app.rag.indexer")

    hits_by_type = defaultdict(list)
    answerable_scores, unanswerable_scores, misses = [], [], []

    for item in items:
        if item["expected_route"] == "blocked":
            continue
        result = retriever.search(item["question"])
        if item["expected_sops"] and not item["expect_no_answer"]:
            found = {c.sop_id for c in result.chunks}
            hit = bool(found & set(item["expected_sops"]))
            hits_by_type[item["type"]].append(hit)
            answerable_scores.append(result.best_vector_score)
            if not hit:
                misses.append((item["id"], item["question"], item["expected_sops"], sorted(found)))
        else:
            unanswerable_scores.append(result.best_vector_score)

    total = [h for v in hits_by_type.values() for h in v]
    print(f"Retrieval hit rate at top {settings.top_k}: {sum(total)}/{len(total)} = {sum(total)/len(total):.0%}")
    for kind, values in sorted(hits_by_type.items()):
        print(f"  {kind:10s} {sum(values)}/{len(values)}")

    if misses:
        print("\nMisses:")
        for qid, question, expected, got in misses:
            print(f"  {qid} {question}\n      expected {expected}, got {got}")

    print("\nBest vector score, questions with an SOP answer:")
    print(f"  min={min(answerable_scores):.3f}  p10={percentile(answerable_scores, 0.1):.3f}  "
          f"mean={statistics.mean(answerable_scores):.3f}")
    if unanswerable_scores:
        print("Best vector score, questions without an SOP answer (no-answer, chitchat, out of scope, escalate-only):")
        print(f"  max={max(unanswerable_scores):.3f}  p90={percentile(unanswerable_scores, 0.9):.3f}  "
              f"mean={statistics.mean(unanswerable_scores):.3f}")
        low, high = max(unanswerable_scores), percentile(answerable_scores, 0.1)
        if low < high:
            print(f"\nSuggested min_vector_score: about {(low + high) / 2:.2f} "
                  f"(between {low:.2f} and {high:.2f}).")
        else:
            print("\nThe two groups overlap. Pick a value near the p10 of answerable questions "
                  "and accept that a few borderline questions will be wrong.")
    print(f"Current min_vector_score: {settings.min_vector_score}")


if __name__ == "__main__":
    main()
