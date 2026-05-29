import time
import traceback
import json
from openai import OpenAI, APIStatusError
from typing import Optional, List, Dict

from .base import BaseLLM
from src.agent.observability import log_llm_call

_RETRY_AFTER_DEFAULT = 10  # NVIDIA NIM is more stable, shorter default wait
_BASE_BACKOFF = 1


class NvidiaLLM(BaseLLM):
    def __init__(
        self,
        api_key: str,
        model: str = "meta/llama-4-maverick-17b-128e-instruct",
        temperature: float = 0.1,
        max_retries: int = 3,
    ):
        if not api_key or api_key.strip() == "":
            raise ValueError("NVIDIA API key is empty or not set")

        self.client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,  # starts with nvapi-
        )

        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Internal helpers  (same pattern as GroqLLM)
    # ------------------------------------------------------------------

    def _retry_after(self, e: APIStatusError) -> float:
        """
        Extract wait time from Retry-After header, or fall back to default.
        """
        headers = getattr(e, "response", None)
        headers = getattr(headers, "headers", {}) if headers else {}
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return _RETRY_AFTER_DEFAULT

    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        memory: Optional[List[Dict[str, str]]],
    ) -> list:
        messages = [{"role": "system", "content": system_prompt}]
        for mem_item in memory or []:
            role = mem_item.get("role", "assistant").lower()
            role = "user" if "user" in role else "assistant"
            messages.append({"role": role, "content": mem_item.get("content", "")})
        messages.append({"role": "user", "content": user_prompt})
        return messages

    # ------------------------------------------------------------------
    # Main generate  (same signature as GroqLLM)
    # ------------------------------------------------------------------

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        memory: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, str]]] = None,
        json_mode: bool = False,
        response_format: Optional[Dict] = None,
    ) -> str:
        last_error = None
        messages = self._build_messages(system_prompt, user_prompt, memory)

        for attempt in range(self.max_retries):
            try:
                started_at = time.perf_counter()

                kwargs: Dict = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                }

                # JSON mode — same behaviour as GroqLLM
                if json_mode:
                    kwargs["response_format"] = response_format or {
                        "type": "json_object"
                    }

                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "none"

                response = self.client.chat.completions.create(**kwargs)
                message = response.choices[0].message

                # Native tool-call response (same shape as GroqLLM)
                if message.tool_calls:
                    tool_call = message.tool_calls[0]
                    output = json.dumps(
                        {
                            "RETRIEVE": True,
                            "tool_name": tool_call.function.name,
                            "tool_inputs": json.loads(tool_call.function.arguments),
                            "selected_columns": None,
                            "ISREL": True,
                            "ISSUP": False,
                            "ISUSE": 0.5,
                            "reasoning": f"LLM issued native tool call: {tool_call.function.name}",
                        }
                    )
                    log_llm_call(
                        provider="nvidia",
                        model=self.model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        memory=memory,
                        tools=tools,
                        response=response,
                        output_text=output,
                        started_at=started_at,
                        extra={
                            "attempt": attempt + 1,
                            "tool_call": tool_call.function.name,
                        },
                    )
                    return output

                output = message.content.strip() if message.content else ""
                log_llm_call(
                    provider="nvidia",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    response=response,
                    output_text=output,
                    started_at=started_at,
                    extra={"attempt": attempt + 1},
                )
                return output

            except APIStatusError as e:
                last_error = e
                log_llm_call(
                    provider="nvidia",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    error=e,
                    extra={"attempt": attempt + 1, "status_code": e.status_code},
                )

                if e.status_code == 429:
                    wait = self._retry_after(e)
                    print(
                        f"[429] NVIDIA rate limited. Waiting {wait}s before retry "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(wait)

                elif e.status_code in (400, 401, 403):
                    print(f"[{e.status_code}] Non-retryable NVIDIA error: {e}")
                    raise

                else:
                    wait = _BASE_BACKOFF * (2**attempt)
                    print(
                        f"[{e.status_code}] NVIDIA server error. Waiting {wait}s "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    traceback.print_exc()
                    time.sleep(wait)

            except Exception as e:
                last_error = e
                log_llm_call(
                    provider="nvidia",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    error=e,
                    extra={"attempt": attempt + 1},
                )
                wait = _BASE_BACKOFF * (2**attempt)
                print(
                    f"[ERROR] NVIDIA error (attempt {attempt + 1}): {e}. "
                    f"Waiting {wait}s"
                )
                traceback.print_exc()
                time.sleep(wait)

        raise RuntimeError(
            f"NVIDIA LLM failed after {self.max_retries} attempts: {last_error}"
        )
