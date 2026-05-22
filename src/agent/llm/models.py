MODELS = {
    # Groq models
    "openai/gpt-oss-20b": {
        "provider": "groq",
        "max_tokens": 8192,
    },
    "llama-3.3-70b-versatile": {
        "provider": "groq",
        "max_tokens": 12000,
    },
    "meta-llama/llama-4-scout-17b-16e-instruct": {
        "provider": "groq",
        "max_tokens": 30000,
    },
    # Ollama models
    "gemma:2b": {"provider": "ollama", "max_tokens": 15000},
    "qwen2.5:7b": {
        "provider": "ollama",
        "max_tokens": 8192,
    },
    "llama3.1:8b": {
        "provider": "ollama",
        "max_tokens": 50000,
    },
    "gemma3:1b": {
        "provider": "ollama",
        "max_tokens": 30000,
    },
}
