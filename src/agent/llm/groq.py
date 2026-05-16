import time
import traceback
import os
from groq import Groq
from .base import BaseLLM
from groq import APIStatusError
from typing import Optional, List, Dict


class GroqLLM(BaseLLM):
    def __init__(
        self, api_key: str, model: str, temperature: float = 0.1, max_retries: int = 3
    ):
        """Initialize Groq LLM with error handling for version conflicts."""
        # Remove proxy env vars that cause issues with groq client
        old_http_proxy = os.environ.pop("HTTP_PROXY", None)
        old_https_proxy = os.environ.pop("HTTPS_PROXY", None)
        old_all_proxy = os.environ.pop("ALL_PROXY", None)

        try:
            # Validate API key before initialization
            if not api_key or api_key.strip() == "":
                raise ValueError("Groq API key is empty or not set")

            self.client = Groq(api_key=api_key)
        except (TypeError, ValueError) as e:
            error_msg = str(e)
            if "proxies" in error_msg.lower():
                # Try again after removing proxy settings
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
                # Re-raise other unexpected errors
                raise
        finally:
            # Restore proxy settings
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
    ) -> str:
        last_error = None

        for attempt in range(self.max_retries):
            try:
                # Build messages list with optional memory context
                messages = [{"role": "system", "content": system_prompt}]

                # Add memory context if provided
                if memory:
                    for mem_item in memory:
                        # Map memory roles to valid Groq roles (system, user, assistant)
                        mem_role = mem_item.get("role", "assistant")
                        if "user" in mem_role.lower():
                            mem_role = "user"
                        elif (
                            "bot" in mem_role.lower() or "assistant" in mem_role.lower()
                        ):
                            mem_role = "assistant"
                        else:
                            # Default to assistant for any other role
                            mem_role = "assistant"

                        messages.append(
                            {
                                "role": mem_role,
                                "content": mem_item.get("content", ""),
                            }
                        )

                # Add user prompt
                messages.append({"role": "user", "content": user_prompt})

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                )
                return response.choices[0].message.content.strip()

            except APIStatusError as e:
                # handle API errors
                print(f"\n❌ Groq APIStatusError (attempt {attempt + 1}):")
                traceback.print_exc()
                last_error = e
                time.sleep(1)

            except Exception as e:
                print(f"\n❌ Groq error (attempt {attempt + 1}):")
                traceback.print_exc()
                last_error = e
                time.sleep(1)

        raise RuntimeError(f"Groq LLM failed: {last_error}")
