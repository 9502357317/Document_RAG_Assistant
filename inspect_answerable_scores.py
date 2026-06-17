import sys
import os

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.services.rag_service import rag_service

answerable_questions = [
    "What forwarding address does the Office of Records notice give for future mail?",
    "Which company consolidated its billing and support at the Main Street headquarters?",
    "What is the total amount due on invoice 4471?",
    "What is the origin warehouse address on shipping manifest 88231?"
]

print("Retrieval scores for answerable questions:\n")
for q in answerable_questions:
    print(f"Question: '{q}'")
    candidates = rag_service.search(q, k=4)
    for c in candidates:
        print(f"  - File: {c['filename']}, Score: {c['score']:.4f}, Text snippet: {c['text'][:100]}...")
    print()
