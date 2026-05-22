import time
import traceback
import os
import json
from groq import Groq
from .base import BaseLLM
from groq import APIStatusError
from typing import Optional, List, Dict

from src.agent.observability import log_llm_call


class GroqLLM(BaseLLM):
    def __init__(
        self, api_key: str, model: str, temperature: float = 0.1, max_retries: int = 3
    ):
        """Initialize Groq LLM with error handling for version conflicts."""
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
                print("[INFO] Please set GROQ_API_KEY environment variable")
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

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        memory: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, str]]] = None,
        json_mode: bool = False,  # NEW: pass True to force JSON output
    ) -> str:
        """
        Generate a response from Groq.

        Args:
            json_mode: When True, sets response_format={"type": "json_object"}.
                       The model is FORCED to return valid JSON — no prose, no markdown.
                       Use this for any node that expects a JSON response (refiner,
                       validator, intent classifier, etc).
                       NOTE: your system prompt must mention "JSON" at least once
                       or Groq will reject the request with a 400 error.
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                started_at = time.perf_counter()
                messages = [{"role": "system", "content": system_prompt}]

                if memory:
                    for mem_item in memory:
                        mem_role = mem_item.get("role", "assistant")
                        if "user" in mem_role.lower():
                            mem_role = "user"
                        elif (
                            "bot" in mem_role.lower() or "assistant" in mem_role.lower()
                        ):
                            mem_role = "assistant"
                        else:
                            mem_role = "assistant"
                        messages.append(
                            {"role": mem_role, "content": mem_item.get("content", "")}
                        )

                messages.append({"role": "user", "content": user_prompt})

                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                }

                # JSON mode — forces valid JSON output, no prose or markdown
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "none"

                response = self.client.chat.completions.create(**kwargs)
                message = response.choices[0].message
                print(message)

                # Native tool call response
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
                print(f"\n❌ Groq APIStatusError (attempt {attempt + 1}):")
                traceback.print_exc()
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
                last_error = e
                time.sleep(1)

            except Exception as e:
                print(f"\n❌ Groq error (attempt {attempt + 1}):")
                traceback.print_exc()
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
                last_error = e
                time.sleep(1)

        raise RuntimeError(f"Groq LLM failed: {last_error}")
