import csv
import sys
import os

# Ensure root folder is in path for imports
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.services.rag_service import embedding_model, collection

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

def recall_at_k(questions: list[dict], k: int = 4) -> float:
    # for each question, check if answer_file is in the top-k filenames
    # return hits / total
    hits = 0
    total = len(questions)
    if total == 0:
        return 0.0

    for idx, item in enumerate(questions):
        q = item["question"]
        expected_file = item["answer_file"]
        
        results = search(q, k=k)
        retrieved_filenames = [r["filename"] for r in results]
        
        if expected_file in retrieved_filenames:
            hits += 1
            print(f"[{idx+1:02d}] HIT  | Question: '{q}' -> Retrieved: {retrieved_filenames} (Expected: {expected_file})")
        else:
            print(f"[{idx+1:02d}] MISS | Question: '{q}' -> Retrieved: {retrieved_filenames} (Expected: {expected_file})")
            
    print(f"\nHits: {hits} / Total: {total}")
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
    
    # Run recall@4
    recall = recall_at_k(questions, k=4)
    print(f"\nrecall@4 = {recall:.2f}  ({len(questions) - int(len(questions)*(1-recall))}/{len(questions)} answerable)")

if __name__ == "__main__":
    main()
