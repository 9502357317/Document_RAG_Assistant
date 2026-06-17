from transformers import pipeline
import torch
torch.set_num_threads(1)



class LLMUnavailable(Exception):
    pass


import os

if os.getenv("TESTING") == "1":
    generator = None
else:
    try:
        generator = pipeline(
            "text-generation",
            model="Qwen/Qwen2.5-0.5B-Instruct"
        )
    except Exception as e:
        raise LLMUnavailable(f"Model loading failed: {e}")


def generate(messages, max_tokens=50):
    try:
        if hasattr(generator, "tokenizer") and generator.tokenizer:
            prompt = generator.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
        else:
            prompt = "\n".join(
                [f"{msg['role']}: {msg['content']}" for msg in messages]
            )

        result = generator(
            prompt,
            max_new_tokens=max_tokens,
            return_full_text=False,
            clean_up_tokenization_spaces=False,
            do_sample=False
        )

        return result[0]["generated_text"]

    except Exception as e:
        raise LLMUnavailable(f"Generation failed: {e}")


if __name__ == "__main__":
    messages = [
        {
            "role": "user",
            "content": "Reply with the word PONG"
        }
    ]

    print(generate(messages))