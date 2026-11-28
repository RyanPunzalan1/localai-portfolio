import ollama

response = ollama.chat(
    model='hermes3',
    messages=[
        {
            'role': 'system', 
            'content': 'You are running locally on the user machine via Ollama. Acknowledge this environment.'
        },
        {
            'role': 'user', 
            'content': 'Confirm you are running locally.'
        }
    ]
)

print(response['message']['content'])