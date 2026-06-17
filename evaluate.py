import csv
import sys
import os
from fastapi.testclient import TestClient

# Ensure root folder is in path for imports
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from main import app

def run(key_path: str) -> dict:
    client = TestClient(app)
    
    print("\nInitializing and indexing corpus...")
    # Reindex corpus in-process to ensure vector DB has all chunks
    reindex_res = client.post("/rag/reindex")
    if reindex_res.status_code != 200:
        print("Error: Reindexing failed", reindex_res.text)
        sys.exit(1)
        
    answerable_questions = []
    unanswerable_questions = []

    # Read CSV
    with open(key_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = row["question"].strip()
            ans_file = row["answer_file"].strip() if "answer_file" in row else ""
            keyphrase = row["expected_keyphrase"].strip() if "expected_keyphrase" in row else ""
            
            if not q:
                continue
                
            if ans_file:
                answerable_questions.append({
                    "question": q,
                    "answer_file": ans_file,
                    "expected_keyphrase": keyphrase
                })
            else:
                unanswerable_questions.append({
                    "question": q
                })

    # Add extra unanswerable questions from Task 8
    extra_unanswerable = [
        "How many employees does the company have?",
        "What is the home address of the engineer named Rivera?",
        "Which airline should we book for the team offsite?",
        "What is the API key for the production embedding service?"
    ]
    for eq in extra_unanswerable:
        if not any(uq["question"] == eq for uq in unanswerable_questions):
            unanswerable_questions.append({"question": eq})

    print(f"\nLoaded {len(answerable_questions)} answerable questions and {len(unanswerable_questions)} unanswerable questions.")

    # 1. Retrieval Metrics: Recall@4 and MRR on answerable questions
    hits = 0
    rr_values = []
    retrieval_hits_map = {} # Maps question string to boolean indicating if correct file was retrieved in top 4

    print("\nEvaluating retrieval metrics...")
    for item in answerable_questions:
        q = item["question"]
        target_file = item["answer_file"]
        
        # Reranked search: N=20 candidates, rerank to top-k=4, rewrite=False by default
        res = client.post("/rag/search", json={"question": q, "k": 4, "rerank": True, "rewrite": False})
        chunks = res.json() if res.status_code == 200 else []
        retrieved_files = [c["filename"] for c in chunks]
        
        # Check recall & reciprocal rank
        if target_file in retrieved_files:
            hits += 1
            idx = retrieved_files.index(target_file)
            rr_values.append(1.0 / (idx + 1))
            retrieval_hits_map[q] = True
        else:
            rr_values.append(0.0)
            retrieval_hits_map[q] = False

    recall = hits / len(answerable_questions) if answerable_questions else 0.0
    mrr = sum(rr_values) / len(answerable_questions) if answerable_questions else 0.0

    # 2. Q&A Metrics: Accuracy on answerable questions & diagnoses
    print("\nEvaluating generation accuracy (this runs LLM, please wait)...")
    accuracy_matches = 0
    diagnoses = []

    for item in answerable_questions:
        q = item["question"]
        target_file = item["answer_file"]
        keyphrase = item["expected_keyphrase"]
        
        # Call full /ask pipeline
        res = client.post("/ask", json={"question": q, "rewrite": False})
        ans_data = res.json() if res.status_code == 200 else {"answer": "", "sources": []}
        generated_answer = ans_data.get("answer", "")
        
        # Check substring match (case-insensitive)
        if keyphrase.lower() in generated_answer.lower():
            accuracy_matches += 1
        else:
            # Check if this was a retrieval hit
            if retrieval_hits_map.get(q, False):
                short_q = q[:47] + "..." if len(q) > 50 else q
                diagnoses.append(
                    f"  - '{short_q}': right file retrieved but answer missed '{keyphrase}'"
                )

    answer_accuracy = accuracy_matches / len(answerable_questions) if answerable_questions else 0.0

    # 3. Refusal Rate on unanswerable questions
    print("\nEvaluating refusal rate on unanswerable questions...")
    refusal_matches = 0
    
    for item in unanswerable_questions:
        q = item["question"]
        res = client.post("/ask", json={"question": q, "rewrite": False})
        ans_data = res.json() if res.status_code == 200 else {"answer": ""}
        generated_answer = ans_data.get("answer", "")
        
        # Correct refusal if contains "I don't know"
        if "i don't know" in generated_answer.lower():
            refusal_matches += 1

    refusal_rate = refusal_matches / len(unanswerable_questions) if unanswerable_questions else 0.0

    # 4. Weakest metric calculation
    metrics = {
        "recall@4": recall,
        "MRR": mrr,
        "answer_accuracy": answer_accuracy,
        "refusal_rate": refusal_rate
    }
    weakest_name = min(metrics, key=metrics.get)
    weakest_score = metrics[weakest_name]
    weakest_str = f"{weakest_name} ({weakest_score:.3f})"

    return {
        "recall@4": recall,
        "MRR": mrr,
        "answer_accuracy": answer_accuracy,
        "refusal_rate": refusal_rate,
        "weakest_metric": weakest_str,
        "diagnoses": diagnoses,
        "answerable_count": len(answerable_questions),
        "unanswerable_count": len(unanswerable_questions)
    }

if __name__ == "__main__":
    csv_path = "rag_questions_sample_key.csv"
    results = run(csv_path)
    
    print("\n" + "="*40)
    print("RAG SCORECARD")
    print("="*40)
    print(f"  recall@4           {results['recall@4']:.3f}")
    print(f"  MRR                {results['MRR']:.3f}")
    print(f"  answer_accuracy    {results['answer_accuracy']:.3f}")
    print(f"  refusal_rate       {results['refusal_rate']:.3f}")
    print()
    print(f"  answerable: {results['answerable_count']}   unanswerable: {results['unanswerable_count']}")
    print(f"  weakest metric: {results['weakest_metric']}")
    print()
    print("Retrieval-hit / answer-miss diagnoses:")
    if results['diagnoses']:
        for diag in results['diagnoses']:
            print(diag)
    else:
        print("  None")
    print("="*40)
