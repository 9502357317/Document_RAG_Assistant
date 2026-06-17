import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.services.rag_service import rag_service

unanswerable_questions = [
    "What was the company's total annual revenue in 2025?",
    "Who is the chief executive officer of Riverside Office Supplies?",
    "What time does the New York office close on public holidays?",
    "What is the Wi-Fi password for the Tokyo office?",
    "How many employees does the company have?",
    "What is the home address of the engineer named Rivera?",
    "Which airline should we book for the team offsite?",
    "What is the API key for the production embedding service?"
]

answerable_questions = [
    "What forwarding address does the Office of Records notice give for future mail?",
    "Which company consolidated its billing and support at the Main Street headquarters?",
    "What is the total amount due on invoice 4471?",
    "What is the origin warehouse address on shipping manifest 88231?"
]

print("RERANK SCORES FOR UNANSWERABLE QUESTIONS:\n")
for q in unanswerable_questions:
    print(f"Question: '{q}'")
    candidates = rag_service.search(q, k=20)
    reranked = rag_service.rerank(q, candidates, k=4)
    for r in reranked:
        print(f"  - File: {r['filename']}, Rerank Score: {r['rerank_score']:.4f}, Text: {r['text'][:80]}...")
    print()

print("\nRERANK SCORES FOR ANSWERABLE QUESTIONS:\n")
for q in answerable_questions:
    print(f"Question: '{q}'")
    candidates = rag_service.search(q, k=20)
    reranked = rag_service.rerank(q, candidates, k=4)
    for r in reranked:
        print(f"  - File: {r['filename']}, Rerank Score: {r['rerank_score']:.4f}, Text: {r['text'][:80]}...")
    print()
