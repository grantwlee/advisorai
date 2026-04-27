#!/bin/sh
set -eu

MODEL="${LLM_MODEL:-qwen2.5:7b}"
PLANNING_MODEL="${LLM_PLANNING_MODEL:-}"

ollama serve &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}

trap cleanup INT TERM

until ollama list >/dev/null 2>&1; do
  echo "Waiting for Ollama server to become ready..."
  sleep 2
done

pull_model() {
  TARGET_MODEL="$1"
  until ollama pull "$TARGET_MODEL"; do
    echo "Waiting for Ollama model pull to succeed for $TARGET_MODEL..."
    sleep 5
  done
  echo "Ollama model $TARGET_MODEL is ready."
}

pull_model "$MODEL"

if [ -n "$PLANNING_MODEL" ] && [ "$PLANNING_MODEL" != "$MODEL" ]; then
  pull_model "$PLANNING_MODEL"
fi

wait "$SERVER_PID"
