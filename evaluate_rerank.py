import csv
import sys
import os

# Ensure root folder is in path for imports
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.services.rag_service import embedding_model, collection, reranker_model

def search(question: str, k: int = 4) -> list[dict]:
    # embed the question, query the vector store, return top-k results
    query_embedding = embedding_model.encode([question])[0].tolist()
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k
    )
    
    candidates = []
    if not results or not results["documents"] or len(results["documents"][0]) == 0:
        return candidates

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    for doc, meta, dist in zip(documents, metadatas, distances):
        # Convert Chroma distance to 0-1 similarity score: score = 1.0 - distance
        score = 1.0 - dist
        candidates.append({
            "filename": meta["filename"],
            "score": score,
            "text": doc
        })
        
    return candidates

def mrr_no_rerank(questions: list[dict], k: int = 4) -> float:
    # for each question: search top-k with bi-encoder only
    # find position of correct file in those k results
    # reciprocal rank = 1 / position (0 if not found)
    # return average reciprocal rank
    rr_sum = 0.0
    total = len(questions)
    if total == 0:
        return 0.0
        
    for item in questions:
        q = item["question"]
        expected_file = item["answer_file"]
        
        results = search(q, k=k)
        retrieved_filenames = [r["filename"] for r in results]
        
        if expected_file in retrieved_filenames:
            pos = retrieved_filenames.index(expected_file) + 1
            rr_sum += 1.0 / pos
            
    return rr_sum / total

def retrieve_wide(question: str, n: int = 20) -> list[dict]:
    # same as search() but fetch n=20 candidates
    return search(question, k=n)

def rerank(question: str, candidates: list[dict], k: int = 4) -> list[dict]:
    # score each (question, chunk) pair with the cross-encoder
    # sort by cross-encoder score, return top k
    if not candidates:
        return []
        
    pairs = [[question, cand["text"]] for cand in candidates]
    scores = reranker_model.predict(pairs)
    
    for cand, score in zip(candidates, scores):
        cand["rerank_score"] = float(score)
        
    sorted_candidates = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)
    return sorted_candidates[:k]

def mrr_reranked(questions: list[dict], k: int = 4) -> float:
    # for each question: wide fetch -> rerank -> find position of correct file
    # reciprocal rank = 1 / position (0 if not found)
    # return average reciprocal rank
    rr_sum = 0.0
    total = len(questions)
    if total == 0:
        return 0.0
        
    for item in questions:
        q = item["question"]
        expected_file = item["answer_file"]
        
        candidates = retrieve_wide(q, n=20)
        reranked = rerank(q, candidates, k=k)
        retrieved_filenames = [r["filename"] for r in reranked]
        
        if expected_file in retrieved_filenames:
            pos = retrieved_filenames.index(expected_file) + 1
            rr_sum += 1.0 / pos
            
    return rr_sum / total

def recall_at_k_no_rerank(questions: list[dict], k: int = 4) -> float:
    hits = 0
    total = len(questions)
    if total == 0:
        return 0.0
        
    for item in questions:
        q = item["question"]
        expected_file = item["answer_file"]
        
        results = search(q, k=k)
        retrieved_filenames = [r["filename"] for r in results]
        
        if expected_file in retrieved_filenames:
            hits += 1
            
    return hits / total

def recall_at_k_reranked(questions: list[dict], k: int = 4) -> float:
    hits = 0
    total = len(questions)
    if total == 0:
        return 0.0
        
    for item in questions:
        q = item["question"]
        expected_file = item["answer_file"]
        
        candidates = retrieve_wide(q, n=20)
        reranked = rerank(q, candidates, k=k)
        retrieved_filenames = [r["filename"] for r in reranked]
        
        if expected_file in retrieved_filenames:
            hits += 1
            
    return hits / total

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
            
            # Skip rows with blank answer_file
            if q and ans_file:
                questions.append({
                    "question": q,
                    "answer_file": ans_file
                })
                
    print(f"Loaded {len(questions)} answerable questions.")
    print("Evaluating metrics with and without reranker...")
    
    # Run evaluation
    rec_no_rerank = recall_at_k_no_rerank(questions, k=4)
    rec_rerank = recall_at_k_reranked(questions, k=4)
    
    mrr_no = mrr_no_rerank(questions, k=4)
    mrr_re = mrr_reranked(questions, k=4)
    
    print("\n" + "="*40)
    print("Task 6 Reranking Evaluation Report")
    print("="*40)
    print(f"questions: {len(questions)}")
    print(f"recall@4    no-rerank: {rec_no_rerank:.2f}    rerank: {rec_rerank:.2f}")
    print(f"MRR         no-rerank: {mrr_no:.3f}   rerank: {mrr_re:.3f}")
    print("="*40)

if __name__ == "__main__":
    main()
