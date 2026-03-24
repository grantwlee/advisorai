#!/bin/sh
set -eu

MODEL="${LLM_MODEL:-llama3.2:3b}"

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

until ollama pull "$MODEL"; do
  echo "Waiting for Ollama model pull to succeed for $MODEL..."
  sleep 5
done

echo "Ollama model $MODEL is ready."

wait "$SERVER_PID"
