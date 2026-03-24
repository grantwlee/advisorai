import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


BASE_URL = os.getenv("EVAL_BASE_URL", "http://localhost/api")
CASES_PATH = Path(__file__).resolve().parent.parent / "evals" / "query_eval_cases.json"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "evals" / "latest_eval_results.json"


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def mentions_year(answer: str) -> bool:
    return bool(re.search(r"(20\d{2}-20\d{2}|\d{2}-\d{2})", answer or ""))


def main() -> int:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []

    for case in cases:
        payload = {
            "question": case["question"],
            "student_id": case.get("student_id"),
            "top_k": case.get("top_k", 5),
        }
        try:
            response = post_json(f"{BASE_URL}/query", payload)
            error = None
        except urllib.error.URLError as exc:
            response = {}
            error = str(exc)

        status_ok = response.get("status") == case["expected_status"]
        citations_ok = True
        if case.get("requires_citations"):
            citations_ok = bool(response.get("citations"))
        year_ok = True
        if case.get("requires_year_mention"):
            year_ok = mentions_year(response.get("answer", ""))

        passed = error is None and status_ok and citations_ok and year_ok
        results.append(
            {
                "id": case["id"],
                "passed": passed,
                "status_ok": status_ok,
                "citations_ok": citations_ok,
                "year_ok": year_ok,
                "latency_ms": response.get("timings_ms", {}).get("total"),
                "response_status": response.get("status"),
                "error": error,
            }
        )

    latencies = [row["latency_ms"] for row in results if isinstance(row["latency_ms"], int)]
    summary = {
        "base_url": BASE_URL,
        "passed": sum(1 for row in results if row["passed"]),
        "total": len(results),
        "accuracy": round(
            sum(1 for row in results if row["passed"]) / len(results), 3
        ) if results else 0,
        "average_latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "results": results,
    }
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
