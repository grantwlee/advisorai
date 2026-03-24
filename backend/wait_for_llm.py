import json
import os
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    base_url = os.getenv("LLM_BASE_URL", "http://llm:11434").rstrip("/")
    model = os.getenv("LLM_MODEL", "llama3.2:3b")
    timeout_seconds = float(os.getenv("LLM_STARTUP_TIMEOUT_SECONDS", "600"))
    poll_interval = float(os.getenv("LLM_STARTUP_POLL_SECONDS", "5"))
    deadline = time.time() + timeout_seconds
    url = f"{base_url}/api/tags"

    print(f"Waiting for LLM model '{model}' at {url} ...", flush=True)

    while time.time() < deadline:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            model_names = [row.get("name") for row in payload.get("models", [])]
            if model in model_names:
                print(f"LLM model '{model}' is available.", flush=True)
                return 0
            print(
                f"LLM reachable, but model '{model}' is not available yet. Found: {model_names}",
                flush=True,
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"LLM not ready yet: {exc}", flush=True)

        time.sleep(poll_interval)

    print(
        f"Timed out after {int(timeout_seconds)}s waiting for LLM model '{model}' at {base_url}.",
        file=sys.stderr,
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
