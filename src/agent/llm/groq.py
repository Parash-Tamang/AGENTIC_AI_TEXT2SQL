import time
import traceback
import os
import json
from groq import Groq
from .base import BaseLLM
from groq import APIStatusError
from typing import Optional, List, Dict

from src.agent.observability import log_llm_call

# Groq free tier limits — adjust to your plan
_RETRY_AFTER_DEFAULT = 30  # seconds to wait on 429 if header is missing
_BASE_BACKOFF = 1  # seconds for non-429 errors


class GroqLLM(BaseLLM):
    def __init__(
        self, api_key: str, model: str, temperature: float = 0.1, max_retries: int = 3
    ):
        old_http_proxy = os.environ.pop("HTTP_PROXY", None)
        old_https_proxy = os.environ.pop("HTTPS_PROXY", None)
        old_all_proxy = os.environ.pop("ALL_PROXY", None)

        try:
            if not api_key or api_key.strip() == "":
                raise ValueError("Groq API key is empty or not set")
            self.client = Groq(api_key=api_key)
        except (TypeError, ValueError) as e:
            error_msg = str(e)
            if "proxies" in error_msg.lower():
                print(f"[WARNING] Groq initialization failed: {e}")
                print("[INFO] Retrying after removing proxy env vars...")
                try:
                    self.client = Groq(api_key=api_key)
                except Exception as retry_error:
                    print(f"[ERROR] Groq retry failed: {retry_error}")
                    raise
            elif (
                "api_key" in error_msg.lower() or "authentication" in error_msg.lower()
            ):
                print(f"[ERROR] Groq API key error: {e}")
                raise
            else:
                raise
        finally:
            if old_http_proxy:
                os.environ["HTTP_PROXY"] = old_http_proxy
            if old_https_proxy:
                os.environ["HTTPS_PROXY"] = old_https_proxy
            if old_all_proxy:
                os.environ["ALL_PROXY"] = old_all_proxy

        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _retry_after(self, e: APIStatusError) -> float:
        """
        Extract wait time from Retry-After header, or fall back to default.
        Groq usually sends 'retry-after' (seconds) on 429 responses.
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
            if "user" in role:
                role = "user"
            else:
                role = "assistant"
            messages.append({"role": role, "content": mem_item.get("content", "")})
        messages.append({"role": "user", "content": user_prompt})
        return messages

    # ------------------------------------------------------------------
    # Main generate
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

                # JSON mode — default to {"type": "json_object"} if no
                # custom format supplied.  Caller must mention "JSON" in
                # the system prompt or Groq returns a 400.
                if json_mode:
                    kwargs["response_format"] = response_format or {
                        "type": "json_object"
                    }

                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "none"

                response = self.client.chat.completions.create(**kwargs)
                message = response.choices[0].message

                # Native tool-call response
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
                        provider="groq",
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
                    provider="groq",
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
                    provider="groq",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    error=e,
                    extra={"attempt": attempt + 1, "status_code": e.status_code},
                )

                if e.status_code == 429:
                    # Rate limited — respect Retry-After, don't burn attempts
                    wait = self._retry_after(e)
                    print(
                        f"[429] Rate limited. Waiting {wait}s before retry "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(wait)

                elif e.status_code in (400, 401, 403):
                    # Non-retryable — fail immediately
                    print(f"[{e.status_code}] Non-retryable error: {e}")
                    raise

                else:
                    # 5xx or other — exponential back-off
                    wait = _BASE_BACKOFF * (2**attempt)
                    print(
                        f"[{e.status_code}] Server error. Waiting {wait}s "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    traceback.print_exc()
                    time.sleep(wait)

            except Exception as e:
                last_error = e
                log_llm_call(
                    provider="groq",
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
                    f"[ERROR] Groq error (attempt {attempt + 1}): {e}. "
                    f"Waiting {wait}s"
                )
                traceback.print_exc()
                time.sleep(wait)

        raise RuntimeError(
            f"Groq LLM failed after {self.max_retries} attempts: {last_error}"
        )
