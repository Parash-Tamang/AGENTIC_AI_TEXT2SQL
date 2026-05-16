from ..config import Settings
from .models import MODELS
from .groq import GroqLLM


def get_llm(model_name: str | None = None):
    """
    Returns an LLM instance based on model name.
    This is your DI entry point.
    """
    model_name = model_name or Settings.DEFAULT_LLM_MODEL
    if model_name not in MODELS:
        raise ValueError(f"Unknown model: {model_name}")

    cfg = MODELS[model_name]

    if cfg["provider"] == "groq":
        return GroqLLM(
            api_key=Settings.GROQ_API_KEY,
            model=model_name,
        )

    raise ValueError(f"Provider not supported: {cfg['provider']}")
