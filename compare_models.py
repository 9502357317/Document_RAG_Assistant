import os
import sys
import time
import csv
from fastapi.testclient import TestClient
from transformers import pipeline

# Ensure root folder is in path for imports
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.append(PROJECT_ROOT)

from main import app
import app.services.llm

def evaluate_model(model_name: str, key_path: str) -> dict:
    print(f"\n==================================================")
    print(f"Loading model: {model_name}...")
    print(f"==================================================")
    
    # Switch the global generator in the llm module to the selected model
    try:
        app.services.llm.generator = pipeline(
            "text-generation",
            model=model_name
        )
    except Exception as e:
        print(f"Error loading model {model_name}: {e}")
        return None

    client = TestClient(app)
    
    # Reindex vector DB (ensures Chroma is updated)
    client.post("/rag/reindex")

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

    # Measure Q&A Accuracy & Latency
    print(f"Evaluating Q&A accuracy over {len(answerable_questions)} questions...")
    latencies = []
    accuracy_matches = 0

    for item in answerable_questions:
        q = item["question"]
        keyphrase = item["expected_keyphrase"]
        
        start_time = time.time()
        res = client.post("/ask", json={"question": q, "rewrite": False})
        latency = (time.time() - start_time) * 1000.0
        latencies.append(latency)
        
        ans_data = res.json() if res.status_code == 200 else {"answer": ""}
        generated_answer = ans_data.get("answer", "")
        
        if keyphrase.lower() in generated_answer.lower():
            accuracy_matches += 1

    accuracy = accuracy_matches / len(answerable_questions) if answerable_questions else 0.0

    # Measure Refusal Rate on unanswerable questions
    print(f"Evaluating refusal rate over {len(unanswerable_questions)} unanswerable questions...")
    refusal_matches = 0

    for item in unanswerable_questions:
        q = item["question"]
        
        res = client.post("/ask", json={"question": q, "rewrite": False})
        ans_data = res.json() if res.status_code == 200 else {"answer": ""}
        generated_answer = ans_data.get("answer", "")
        
        if "i don't know" in generated_answer.lower():
            refusal_matches += 1

    refusal_rate = refusal_matches / len(unanswerable_questions) if unanswerable_questions else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    return {
        "accuracy": accuracy,
        "refusal_rate": refusal_rate,
        "avg_latency_ms": avg_latency
    }

def main():
    csv_path = "rag_questions_sample_key.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        sys.exit(1)

    # We evaluate both models
    models = {
        "Qwen/Qwen2.5-0.5B-Instruct": None,
        "Qwen/Qwen2.5-1.5B-Instruct": None
    }

    for model_name in models.keys():
        results = evaluate_model(model_name, csv_path)
        if results:
            models[model_name] = results

    # Print Comparison Table
    print("\n" + "="*60)
    print("MODEL COMPARISON SCORECARD")
    print("="*60)
    print(f"{'Metric':<25} | {'Qwen2.5-0.5B':<15} | {'Qwen2.5-1.5B':<15}")
    print("-" * 60)
    
    m0_acc = f"{models['Qwen/Qwen2.5-0.5B-Instruct']['accuracy']:.1%}" if models["Qwen/Qwen2.5-0.5B-Instruct"] else "N/A"
    m1_acc = f"{models['Qwen/Qwen2.5-1.5B-Instruct']['accuracy']:.1%}" if models["Qwen/Qwen2.5-1.5B-Instruct"] else "N/A"
    print(f"{'Answer Accuracy':<25} | {m0_acc:<15} | {m1_acc:<15}")
    
    m0_ref = f"{models['Qwen/Qwen2.5-0.5B-Instruct']['refusal_rate']:.1%}" if models["Qwen/Qwen2.5-0.5B-Instruct"] else "N/A"
    m1_ref = f"{models['Qwen/Qwen2.5-1.5B-Instruct']['refusal_rate']:.1%}" if models["Qwen/Qwen2.5-1.5B-Instruct"] else "N/A"
    print(f"{'Refusal Rate':<25} | {m0_ref:<15} | {m1_ref:<15}")
    
    m0_lat = f"{models['Qwen/Qwen2.5-0.5B-Instruct']['avg_latency_ms']:.1f} ms" if models["Qwen/Qwen2.5-0.5B-Instruct"] else "N/A"
    m1_lat = f"{models['Qwen/Qwen2.5-1.5B-Instruct']['avg_latency_ms']:.1f} ms" if models["Qwen/Qwen2.5-1.5B-Instruct"] else "N/A"
    print(f"{'Avg Q&A Latency':<25} | {m0_lat:<15} | {m1_lat:<15}")
    print("="*60)

if __name__ == "__main__":
    main()
