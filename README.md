# AdvisorAI

AdvisorAI is a Flask + PostgreSQL + Flutter web app that retrieves Andrews bulletin chunks, generates cited answers with a local LLM, verifies those citations, and supports a scoped student-profile advising flow.

## Stack

- `backend/`: Flask API, retrieval, verifier, student profile logic, eval scripts
- `frontend/advisorai_web/`: Flutter web source
- `apache/`: built web assets served by Apache with `/api` proxied to Flask
- `data/bulletins/processed/`: FAISS index and chunk metadata

## Local Run

1. Start the core services:

```bash
docker compose up -d db llm backend apache
```

2. Initialize the relational schema and demo data:

```bash
docker compose exec backend python init_db.py
docker compose exec backend python load_bulletin_chunks.py
```

3. Pull the configured local model into the LLM service:

```bash
docker compose exec llm ollama pull llama3.2:3b
```

4. Run the LLM smoke test:

```bash
docker compose exec backend python scripts/llm_smoke_test.py
```

5. Open the app:

- Frontend: [http://localhost](http://localhost)
- Adminer: [http://localhost:8080](http://localhost:8080)
- LLM API: [http://localhost:11434](http://localhost:11434)

Demo student IDs:

- `S1001` for Computer Science (`2023-2024`)
- `S1002` for Information Systems (`2022-2023`)

## Flutter Build

If you update the Flutter source, rebuild the web bundle and copy it into Apache's static folder:

```bash
cd frontend/advisorai_web
flutter build web --release
rsync -a --delete build/web/ ../../apache/web/
```

## API Highlights

- `GET /api/retrieve`
- `POST /api/query`
- `GET /api/students/<student_id>`
- `POST /api/students/<student_id>/courses`
- `DELETE /api/students/<student_id>/courses/<record_id>`

`POST /api/query` accepts:

```json
{
  "question": "What do I have left?",
  "student_id": "S1001",
  "top_k": 5
}
```

The response includes `status`, `answer`, `refusal_reason`, `citations`, `retrieved_chunks`, `verifier`, and `timings_ms`.

## Evaluation

Run the saved eval set against the live backend:

```bash
docker compose exec backend python scripts/run_eval.py
```

Results are written to `backend/evals/latest_eval_results.json`.

## Tests

Run the lightweight regression tests from the backend directory:

```bash
cd backend
python -m unittest discover tests
```
