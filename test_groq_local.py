import os
from dotenv import load_dotenv

load_dotenv(".env")

from groq import Groq

api_key = os.environ.get("GROQ_API_KEY")
print("=== GROQ API LOCAL TEST ===")
print(f"API Key: {api_key[:12]}...{api_key[-4:]}")
model = "openai/gpt-oss-120b"
print(f"Target Model: {model}")

client = Groq(api_key=api_key)

completion = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "system", "content": "You are a technical recruiting assistant."},
        {"role": "user", "content": 'Generate a 1-sentence verification response in JSON format with keys: "status", "message".'}
    ],
    response_format={"type": "json_object"},
    temperature=0.0
)

print("\n--- Raw Response Content ---")
print(completion.choices[0].message.content)

usage = completion.usage
print("\n--- Token Usage & Performance ---")
print(f"Total Tokens: {usage.total_tokens} (Prompt: {usage.prompt_tokens}, Completion: {usage.completion_tokens})")
print(f"Queue Time: {usage.queue_time:.4f}s | Completion Time: {usage.completion_time:.4f}s")
print("============================")
