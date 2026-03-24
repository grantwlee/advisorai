import json
import os
import socket
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_BASE_URL", "http://llm:11434").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "llama3.2:3b")
        self.timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "180"))
        self.context_window = int(os.getenv("LLM_CONTEXT_WINDOW", "4096"))

    def health(self) -> dict:
        request = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            raise LLMError(
                f"Timed out reaching LLM service at {self.base_url} after {self.timeout_seconds} seconds."
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Unable to reach LLM service at {self.base_url}: {exc}") from exc

    def generate_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        temperature: float = 0.1,
    ) -> dict:
        payload = {
            "model": self.model,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_predict": self.max_tokens,
                "num_ctx": self.context_window,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LLMError(f"LLM request failed with HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LLMError(
                f"LLM generation timed out after {self.timeout_seconds} seconds for model {self.model}."
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Unable to reach LLM service at {self.base_url}: {exc}") from exc

        raw_response = body.get("response", "").strip()
        if not raw_response:
            raise LLMError("LLM returned an empty response.")

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned invalid JSON: {raw_response}") from exc

        return parsed
