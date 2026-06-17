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

print("Retrieval scores for unanswerable questions:\n")
for q in unanswerable_questions:
    print(f"Question: '{q}'")
    candidates = rag_service.search(q, k=4)
    for c in candidates:
        print(f"  - File: {c['filename']}, Score: {c['score']:.4f}, Text snippet: {c['text'][:100]}...")
    print()
