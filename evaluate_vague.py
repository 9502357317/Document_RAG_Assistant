import sys
import os

# Ensure root folder is in path for imports
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.services.rag_service import rag_service

def evaluate_vague_recall():
    vague_questions = [
        {"question": "dc letter address?", "answer_file": "letter_dc.txt"},
        {"question": "riverside place", "answer_file": "letter_riverside.txt"},
        {"question": "how many days to return", "answer_file": "returns_policy.md"},
        {"question": "who does the tests", "answer_file": "q3_planning_notes.md"},
        {"question": "export csv how", "answer_file": "howto_export_registry.md"},
        {"question": "boulevard short form", "answer_file": "address_normalization_spec.md"}
    ]

    print("=" * 60)
    print("Evaluating Recall@4 on Vague/Messy Questions")
    print("=" * 60)

    for rewrite in [False, True]:
        print(f"\nConfiguration: Query Rewriting = {rewrite}")
        print("-" * 45)
        hits = 0
        total = len(vague_questions)

        for idx, item in enumerate(vague_questions):
            q = item["question"]
            expected_file = item["answer_file"]

            # Use the app's default search pipeline: fetch N=20 candidates, rerank to top-k=4
            candidates = rag_service.search(q, k=20, rewrite=rewrite)
            results = rag_service.rerank(q, candidates, k=4)
            retrieved_filenames = [r["filename"] for r in results]

            if expected_file in retrieved_filenames:
                hits += 1
                print(f"[{idx+1:02d}] HIT  | Question: '{q}' -> Retrieved: {retrieved_filenames} (Expected: {expected_file})")
            else:
                print(f"[{idx+1:02d}] MISS | Question: '{q}' -> Retrieved: {retrieved_filenames} (Expected: {expected_file})")

        recall = hits / total
        print(f"\nRecall@4 (with rewrite={rewrite}) = {recall:.4f} ({hits}/{total})")

if __name__ == "__main__":
    evaluate_vague_recall()