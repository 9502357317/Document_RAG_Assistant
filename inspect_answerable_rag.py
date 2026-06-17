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

print("Testing answerable questions with full RAG /ask:\n")
for q in answerable_questions:
    res = rag_service.ask(q, rewrite=False)
    print(f"Question:   '{q}'")
    print(f"Answer:     \"{res.get('answer')}\"")
    print(f"Sources:    {res.get('sources')}")
    print(f"Ctx Found:  {res.get('context_found')}")
    print()
