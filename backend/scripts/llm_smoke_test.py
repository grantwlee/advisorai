import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.llm_client import LLMError, OllamaClient


def main() -> int:
    print(f"Python OK: {sys.version.split()[0]}")
    client = OllamaClient()

    try:
        tags = client.health()
    except LLMError as exc:
        print(f"LLM health check failed: {exc}")
        return 1

    model_names = [row.get("name") for row in tags.get("models", [])]
    print(f"LLM endpoint OK: {client.base_url}")
    print(f"Available models: {model_names}")

    if client.model not in model_names:
        print(
            "Configured model is not available yet. "
            f"Pull it first with: docker compose exec llm ollama pull {client.model}"
        )
        return 1

    try:
        result = client.generate_json(
            system_prompt=(
                "Return JSON with keys status, answer, refusal_reason. "
                "Use status answered and write one short sentence."
            ),
            prompt="Say hello from the smoke test.",
            temperature=0,
        )
    except LLMError as exc:
        print(f"Generation failed: {exc}")
        return 1

    print("Generation OK:")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
