import os
import ollama

# Define the local file path
file_path = 'sample.txt'

# Check if the file exists locally before processing
if os.path.exists(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        file_content = f.read()

    print(f"[*] Successfully read local file: {file_path}\n")

    # Send the file contents securely to your local Hermes 3 model
    response = ollama.chat(
        model='hermes3',
        messages=[
            {
                'role': 'system',
                'content': 'You are a secure, local-first file processing assistant running completely offline.'
            },
            {
                'role': 'user',
                'content': f'Please analyze and summarize the following local file content:\n\n{file_content}'
            }
        ]
    )

    print("--- Local Agent Response ---")
    print(response['message']['content'])
else:
    print(f"[!] Error: File '{file_path}' not found.")