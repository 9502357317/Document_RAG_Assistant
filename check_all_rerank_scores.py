import csv
import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.services.rag_service import rag_service

def main():
    csv_path = "rag_questions_sample_key.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        sys.exit(1)
        
    questions = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = row["question"].strip()
            ans_file = row["answer_file"].strip()
            if q and ans_file:
                questions.append({
                    "question": q,
                    "answer_file": ans_file
                })

    print(f"Loaded {len(questions)} answerable questions.")
    print("Evaluating top rerank scores...\n")
    
    below_5 = []
    for idx, item in enumerate(questions):
        q = item["question"]
        expected_file = item["answer_file"]
        
        candidates = rag_service.search(q, k=20)
        reranked = rag_service.rerank(q, candidates, k=4)
        
        if reranked:
            top_score = reranked[0]["rerank_score"]
            top_file = reranked[0]["filename"]
            print(f"[{idx+1:02d}] Top Score: {top_score:7.4f} | Correct File Retrieved? {'YES' if expected_file in [r['filename'] for r in reranked] else 'NO'} | Question: '{q[:50]}...'")
            if top_score < -5.0:
                below_5.append((q, top_score, expected_file))
        else:
            print(f"[{idx+1:02d}] No candidates found for Question: '{q[:50]}...'")

    print("\n" + "="*50)
    print(f"Questions with top rerank score below -5.0 (total: {len(below_5)}):")
    print("="*50)
    for q, score, expected in below_5:
        print(f"Score: {score:.4f} | Expected File: {expected} | Question: '{q}'")

if __name__ == "__main__":
    main()
