import json
import re
from agent_root.app.src.core.llm.registry import get_llm
from agent_root.app.src.agent.llm_utils import generate_with_estimate


def strip_common_noise(text: str) -> str:
    """
    Remove common LLM noise without touching JSON content.
    """
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "")
    return text.strip()


def extract_first_json_object(text: str) -> dict:
    """
    Extract the first valid JSON object.
    Fully supports nested dicts and arrays.
    """
    decoder = json.JSONDecoder()

    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found")

    while start < len(text):
        try:
            obj, _ = decoder.raw_decode(text[start:])
            return obj
        except json.JSONDecodeError:
            start = text.find("{", start + 1)

    raise ValueError("Failed to extract valid JSON object")


def parse_llm_json(raw_text: str) -> dict:
    """
    Deterministic JSON parsing for LLM outputs.
    """
    response = strip_common_noise(raw_text)
    return extract_first_json_object(response)


def fix_json_with_llm(raw_text: str) -> dict:

    system_message = """You are a strict JSON normalizer. "
                    "Extract the FIRST JSON object only. "
                    "Remove explanations and markdown. "
                    "Fix JSON syntax ONLY (NULL → null). "
                    "Do NOT change structure or meaning. "
                    "Output ONLY valid JSON."""
    llm = get_llm()
    response, token_info = generate_with_estimate(
        llm,
        system_prompt=system_message,
        user_prompt=raw_text,
        step_name="fix_json_with_llm",
    )
    print(f"🔎 fix_json_with_llm token info: {token_info}")

    # 🔥 CRITICAL: extract JSON, don't parse whole string
    decoder = json.JSONDecoder()
    start = response.find("{")
    if start == -1:
        raise ValueError("LLM-2 returned no JSON")

    while start < len(response):
        try:
            obj, _ = decoder.raw_decode(response[start:])
            return obj
        except json.JSONDecodeError:
            start = response.find("{", start + 1)

    raise ValueError("Failed to extract valid JSON from LLM-2 output")
