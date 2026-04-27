# AdvisorAI

AdvisorAI is a containerized academic advising application that combines a Flutter web client, a Flask API, PostgreSQL-backed student data, retrieval over Andrews University bulletin content, and a local Ollama-hosted LLM. The product is designed to answer bulletin-grounded advising questions, manage student course history, and support scoped degree-audit and next-course planning workflows.

## What The Product Does

- Serves a web interface for students and advisors.
- Stores student profiles, course catalog records, tracked course history, and advising notes in PostgreSQL.
- Retrieves bulletin evidence from preprocessed Andrews bulletin PDFs using hybrid semantic plus keyword search.
- Generates short grounded answers with inline chunk citations through Ollama.
- Verifies that each answer sentence is supported by retrieved evidence before returning it.
- Supports scoped degree-audit summaries and next-term planning for configured demo programs.

## Architecture

### Runtime services

- `frontend/advisorai_web/`: Flutter web application.
- `apache/`: Apache HTTP server that serves the built Flutter bundle and reverse proxies `/api` to Flask.
- `backend/`: Flask application, retrieval orchestration, LLM client, verification, degree-audit logic, and seed/eval scripts.
- `db`: PostgreSQL 16 for application data and keyword retrieval over bulletin chunks.
- `llm`: Ollama model runtime for local text generation.

### Request flow

1. A browser loads the Flutter app through Apache.
2. The frontend sends `/api` requests through Apache to the Flask backend.
3. The backend reads student state from PostgreSQL.
4. The retrieval layer searches bulletin artifacts with FAISS semantic search and PostgreSQL full-text search.
5. The backend builds a grounded prompt and sends it to Ollama.
6. The verifier checks sentence-level citation support before the API returns the response.

### Retrieval assets

- Raw bulletins live in `data/bulletins/raw/`.
- Processed retrieval artifacts live in `data/bulletins/processed/`.
- The repository currently includes:
  - `bulletin_chunks.jsonl`
  - `bulletin_index.faiss`
  - `bulletin_chunks_manifest.json`

## Repository Map

- `compose.yml`: primary local and containerized runtime definition.
- `backend/app.py`: API entrypoint.
- `backend/services/retrieval_service.py`: semantic, keyword, and hybrid retrieval.
- `backend/services/query_service.py`: prompt assembly, answer generation, verification, and logging.
- `backend/services/degree_audit.py`: configured audit rules and audit summaries.
- `backend/services/planning_service.py`: next-course planning context builder.
- `backend/init_db.py`: schema bootstrap plus demo student and course seed data.
- `backend/load_bulletin_chunks.py`: loads processed bulletin chunks into PostgreSQL for keyword retrieval.
- `tools/bulletin_ingest/ingestBulletin.py`: current bulletin PDF ingestion and FAISS build script.
- `bulletin_pipeline/`: older ingestion prototype, not the main application runtime path.
- `docs/`: architecture, ingestion, and schema reference material.

## Core Features

### Bulletin-grounded advising

- `POST /api/query` answers advising questions from retrieved bulletin evidence only.
- Answers are expected to cite retrieved chunk IDs such as `23-24:007646`.
- If the backend cannot support the answer safely, it returns a refusal instead of guessing.

### Student profile management

- Create and list students.
- Search students by ID, name, or program.
- View student profile details and tracked courses.
- Add, update, or delete student course records.
- Persist advising-session notes.

### Degree audit and planning

- Student-aware question answering narrows retrieval by program and bulletin year.
- Optional degree-audit rules summarize completed, in-progress, and remaining configured requirements.
- Planning questions can recommend eligible next courses based on saved progress and prerequisite rules.

## Local Development

### Prerequisites

- Docker and Docker Compose
- A machine capable of running Ollama locally
- Flutter SDK if you need to rebuild the frontend bundle outside Docker

### Environment variables

Create `.env` from `.env.example` and set values appropriate for your environment.

Required and important variables:

- `DATABASE_URL`: PostgreSQL connection string used by the backend.
- `LLM_BASE_URL`: Ollama base URL.
- `LLM_MODEL`: model to serve through Ollama. The current compose default is `llama3.2:3b`.
- `LLM_TIMEOUT_SECONDS`: request timeout for generation and health calls.
- `LLM_MAX_TOKENS`: generation length cap.
- `LLM_CONTEXT_WINDOW`: Ollama context window.
- `LLM_PROMPT_CHUNK_CHAR_LIMIT`: per-chunk truncation used when assembling prompts.
- `LLM_PROMPT_TOTAL_CHARS`: total retrieval-context cap in prompt assembly.
- `LLM_STARTUP_TIMEOUT_SECONDS`: how long the backend waits for the configured model to become available.
- `LLM_STARTUP_POLL_SECONDS`: poll interval while waiting for Ollama.
- `QUERY_LOG_PATH`: JSONL log destination for query outcomes.
- `RETRIEVAL_DATA_DIR`: optional override for the processed retrieval artifact directory.
- `USE_DEGREE_AUDIT_RULES`: enables rule-backed audit and planning behavior when set to a truthy value.

### Start the stack

```bash
docker compose up -d db llm backend apache
```

Optional local admin UI:

```bash
docker compose up -d adminer
```

### Initialize the application data

1. Bootstrap schema and demo records:

```bash
docker compose exec backend python init_db.py
```

2. Load processed bulletin chunks into PostgreSQL for keyword and hybrid retrieval:

```bash
docker compose exec backend python load_bulletin_chunks.py
```

3. Pull the configured Ollama model if it is not already present:

```bash
docker compose exec llm ollama pull llama3.2:3b
```

4. Verify LLM connectivity:

```bash
docker compose exec backend python scripts/llm_smoke_test.py
```

### Access the application

- Web app: [http://localhost](http://localhost)
- Backend health: [http://localhost/api/health](http://localhost/api/health)
- Adminer: [http://localhost:8080](http://localhost:8080)
- Ollama API: [http://localhost:11434](http://localhost:11434)

Demo student IDs seeded by `backend/init_db.py` include:

- `S1001`
- `S1002`
- `S1003`
- `S1004`
- `S1005`
- `S1006`

## Frontend Build

Apache serves the built Flutter web bundle. In Docker Compose, Apache mounts `frontend/advisorai_web/build/web` directly into the container, so rebuild the frontend whenever web code changes:

```bash
cd frontend/advisorai_web
flutter pub get
flutter build web --release
```

If you deploy Apache without the Compose volume mount, make sure the built assets are copied into `apache/web/`.

## Data and Ingestion

The live application reads retrieval artifacts from `data/bulletins/processed/`. If bulletin source files change, regenerate the processed assets before reloading PostgreSQL:

```bash
python tools/bulletin_ingest/ingestBulletin.py
docker compose exec backend python load_bulletin_chunks.py
```

The current ingestion script:

- reads PDFs from `data/bulletins/raw/`
- removes repeated header and footer content
- chunks cleaned text into retrieval windows
- embeds chunks with `sentence-transformers/all-MiniLM-L6-v2`
- writes FAISS and JSONL outputs used at runtime

## Quality and Verification

### Automated checks

- Backend unit tests:

```bash
cd backend
python -m unittest discover tests
```

- Saved evaluation suite against a running backend:

```bash
docker compose exec backend python scripts/run_eval.py
```

Evaluation results are written to `backend/evals/latest_eval_results.json`.

## Known Gaps

- Authentication and RBAC are not implemented.
- Degree-audit coverage is scoped to configured demo programs rather than a full institutional catalog.
- The query logger writes to a local file path by default.
- The frontend bundle is not built automatically as part of the root Compose workflow.
- Some reference docs in `docs/` describe earlier ingestion details and should be treated as supporting context, with the runtime code as the source of truth.

