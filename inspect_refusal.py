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

print("Debugging unanswerable questions /ask pipeline:\n")
refusal_count = 0

for idx, q in enumerate(unanswerable_questions):
    print(f"--- Q{idx+1}: '{q}' ---")
    
    # Run the ask pipeline
    res = rag_service.ask(q, rewrite=False)
    answer = res.get('answer', '')
    sources = res.get('sources', [])
    ctx_found = res.get('context_found', False)
    
    print(f"Answer:     \"{answer}\"")
    print(f"Sources:    {sources}")
    print(f"Ctx Found:  {ctx_found}")
    
    # Under standard refusal instructions, the correct response is "I don't know."
    if "i don't know" in answer.lower():
        refusal_count += 1
        print("Result:     Correctly Refused")
    else:
        print("Result:     Failed to Refuse")
    print()

refusal_rate = refusal_count / len(unanswerable_questions)
print("=" * 40)
print(f"Refusal rate on unanswerable questions: {refusal_rate:.1%}")
print(f"Correctly declined: {refusal_count} out of {len(unanswerable_questions)}")
print("=" * 40)

