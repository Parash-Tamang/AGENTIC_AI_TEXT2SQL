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
    "qwen2.5:3b": {
        "provider": "ollama",
        "max_tokens": 30000,
    },
    "llama3.1:8b": {
        "provider": "ollama",
        "max_tokens": 50000,
    },
    "gemma3:1b": {
        "provider": "ollama",
        "max_tokens": 30000,
    },
    "sqlcoder": {
        "provider": "ollama",
        "max_tokens": 30000,
    },
    # NVIDIA NIM models — verified 200 OK chat completions only
    "abacusai/dracarys-llama-3.1-70b-instruct": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "bytedance/seed-oss-36b-instruct": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "deepseek-ai/deepseek-v4-flash": {"provider": "nvidia", "max_tokens": 32000},
    "google/gemma-2-2b-it": {"provider": "nvidia", "max_tokens": 32000},
    "google/gemma-3n-e2b-it": {"provider": "nvidia", "max_tokens": 32000},
    "google/gemma-3n-e4b-it": {"provider": "nvidia", "max_tokens": 32000},
    "meta/llama-3.1-8b-instruct": {"provider": "nvidia", "max_tokens": 32000},
    "meta/llama-3.2-11b-vision-instruct": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "meta/llama-3.2-1b-instruct": {"provider": "nvidia", "max_tokens": 32000},
    "meta/llama-3.2-3b-instruct": {"provider": "nvidia", "max_tokens": 32000},
    "meta/llama-3.2-90b-vision-instruct": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "meta/llama-3.3-70b-instruct": {"provider": "nvidia", "max_tokens": 32000},
    "meta/llama-4-maverick-17b-128e-instruct": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "meta/llama-guard-4-12b": {"provider": "nvidia", "max_tokens": 32000},
    "mistralai/ministral-14b-instruct-2512": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "mistralai/mistral-7b-instruct-v0.3": {"provider": "nvidia", "max_tokens": 32000},
    "mistralai/mistral-small-4-119b-2603": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/llama-3.3-nemotron-super-49b-v1.5": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/gliner-pii": {"provider": "nvidia", "max_tokens": 32000},
    "nvidia/ising-calibration-1-35b-a3b": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/llama-3.1-nemoguard-8b-content-safety": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/llama-3.1-nemoguard-8b-topic-control": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/llama-3.1-nemotron-nano-vl-8b-v1": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/llama-3.1-nemotron-safety-guard-8b-v3": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/llama-3.3-nemotron-super-49b-v1": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/nemotron-3-nano-30b-a3b": {"provider": "nvidia", "max_tokens": 32000},
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/nemotron-3-content-safety": {"provider": "nvidia", "max_tokens": 32000},
    "nvidia/nemotron-3-super-120b-a12b": {"provider": "nvidia", "max_tokens": 32000},
    "nvidia/nemotron-content-safety-reasoning-4b": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "nvidia/nemotron-mini-4b-instruct": {"provider": "nvidia", "max_tokens": 32000},
    "nvidia/nemotron-nano-12b-v2-vl": {"provider": "nvidia", "max_tokens": 32000},
    "nvidia/nvidia-nemotron-nano-9b-v2": {"provider": "nvidia", "max_tokens": 32000},
    "openai/gpt-oss-120b": {"provider": "nvidia", "max_tokens": 32000},
    "qwen/qwen3-next-80b-a3b-instruct": {"provider": "nvidia", "max_tokens": 32000},
    "qwen/qwen3.5-122b-a10b": {"provider": "nvidia", "max_tokens": 32000},
    "sarvamai/sarvam-m": {"provider": "nvidia", "max_tokens": 32000},
    "stepfun-ai/step-3.5-flash": {"provider": "nvidia", "max_tokens": 32000},
    "stepfun-ai/step-3.7-flash": {"provider": "nvidia", "max_tokens": 32000},
    "stockmark/stockmark-2-100b-instruct": {
        "provider": "nvidia",
        "max_tokens": 32000,
    },
    "upstage/solar-10.7b-instruct": {"provider": "nvidia", "max_tokens": 32000},
    "z-ai/glm-5.1": {"provider": "nvidia", "max_tokens": 32000},
}
