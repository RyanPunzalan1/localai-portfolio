import os
import json
import ollama

from safety import clean_history

HISTORY_FILE = "chat_history.json"

print("[*] Initializing local chat agent with persistent memory...")
print("[*] Type 'exit' or 'quit' to end the session.\n")

# Load past conversation history if it exists locally, otherwise start fresh
if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            messages = clean_history(json.load(f))
        if not messages:
            raise ValueError("no valid messages in history file")
        print(f"[*] Loaded previous conversation history ({len(messages)} messages found).")
    except Exception as e:
        print(f"[!] Error loading history: {e}. Starting fresh.")
        messages = [{'role': 'system', 'content': 'You are a secure, local-first personal AI assistant running offline via Ollama.'}]
else:
    messages = [{'role': 'system', 'content': 'You are a secure, local-first personal AI assistant running offline via Ollama.'}]

while True:
    try:
        user_input = input("You: ")
        if user_input.lower() in ['exit', 'quit']:
            print("Saving session and shutting down local agent. Goodbye!")
            break
        
        if not user_input.strip():
            continue

        # Append user message
        messages.append({'role': 'user', 'content': user_input})

        # Send full context to local model
        response = ollama.chat(model='hermes3', messages=messages)
        
        assistant_reply = response['message']['content']
        print(f"\nHermes 3: {assistant_reply}\n")

        # Append assistant response
        messages.append({'role': 'assistant', 'content': assistant_reply})

        # Save updated history locally after every turn
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2)

    except KeyboardInterrupt:
        print("\nSession interrupted. Saving session and exiting.")
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2)
        break