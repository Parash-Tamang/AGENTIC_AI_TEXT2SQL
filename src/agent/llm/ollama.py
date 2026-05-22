import time
import traceback
import json
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional, List, Dict
from .base import BaseLLM

from src.agent.observability import log_llm_call

# Thread-safe singleton session
_session_lock = threading.Lock()
_ollama_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _ollama_session
    if _ollama_session is not None:
        return _ollama_session
    with _session_lock:
        if _ollama_session is None:
            session = requests.Session()
            session.headers.update(
                {
                    "Content-Type": "application/json",
                    "ngrok-skip-browser-warning": "true",
                }
            )
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=20,
                max_retries=Retry(
                    total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]
                ),
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            _ollama_session = session
            print("[INFO] Ollama session created with connection pooling")
    return _ollama_session


class OllamaLLM(BaseLLM):
    def __init__(
        self,
        base_url: str,
        model: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
        timeout: int = 200,
    ):
        if not base_url or base_url.strip() == "":
            raise ValueError("Ollama base_url is empty or not set")

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = _get_session()

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        memory: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, str]]] = None,
    ) -> str:
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

                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_ctx": self.max_tokens,
                    },
                }

                if tools:
                    payload["tools"] = tools

                response = self.session.post(
                    f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                message = response.json()["message"]

                # Native tool call response (same pattern as GroqLLM)
                if message.get("tool_calls"):
                    tool_call = message["tool_calls"][0]
                    output = json.dumps(
                        {
                            "RETRIEVE": True,
                            "tool_name": tool_call["function"]["name"],
                            "tool_inputs": tool_call["function"]["arguments"],
                            "selected_columns": None,
                            "ISREL": True,
                            "ISSUP": False,
                            "ISUSE": 0.5,
                            "reasoning": f"LLM issued native tool call: {tool_call['function']['name']}",
                        }
                    )
                    log_llm_call(
                        provider="ollama",
                        model=self.model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        memory=memory,
                        tools=tools,
                        response=response.json(),
                        output_text=output,
                        started_at=started_at,
                        extra={
                            "attempt": attempt + 1,
                            "tool_call": tool_call["function"]["name"],
                        },
                    )
                    return output

                # Normal text response
                output = message["content"].strip() if message.get("content") else ""
                log_llm_call(
                    provider="ollama",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    response=response.json(),
                    output_text=output,
                    started_at=started_at,
                    extra={"attempt": attempt + 1},
                )
                return output

            except requests.exceptions.Timeout:
                print(f"\n❌ Ollama timeout (attempt {attempt + 1})")
                log_llm_call(
                    provider="ollama",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    error=TimeoutError("Ollama request timed out"),
                    extra={"attempt": attempt + 1},
                )
                last_error = TimeoutError("Ollama request timed out")
                time.sleep(2**attempt)  # exponential backoff

            except requests.exceptions.ConnectionError:
                print(f"\n❌ Ollama connection error (attempt {attempt + 1})")
                log_llm_call(
                    provider="ollama",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    error=ConnectionError("Ollama unreachable"),
                    extra={"attempt": attempt + 1},
                )
                last_error = ConnectionError("Ollama unreachable")
                time.sleep(2**attempt)

            except requests.exceptions.HTTPError as e:
                print(f"\n❌ Ollama HTTPError (attempt {attempt + 1}):")
                traceback.print_exc()
                log_llm_call(
                    provider="ollama",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    error=e,
                    extra={"attempt": attempt + 1},
                )
                last_error = e
                time.sleep(2**attempt)

            except Exception as e:
                print(f"\n❌ Ollama error (attempt {attempt + 1}):")
                traceback.print_exc()
                log_llm_call(
                    provider="ollama",
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    memory=memory,
                    tools=tools,
                    error=e,
                    extra={"attempt": attempt + 1},
                )
                last_error = e
                time.sleep(2**attempt)

        raise RuntimeError(
            f"Ollama LLM failed after {self.max_retries} attempts: {last_error}"
        )
