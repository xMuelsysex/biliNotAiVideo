# Bilibili AI Video Identification

Chrome / Edge Manifest V3 extension and FastAPI service for displaying shared,
explainable AI-content evidence labels on Bilibili videos.

## Requirements

- Python 3.12
- Node.js 20 or newer
- npm 10 or newer

## Backend

```bash
cd backend
uv python install 3.12
uv venv --python 3.12 .venv
. .venv/bin/activate
uv pip install -e '.[dev]'

ruff check .
mypy app
pytest -q
uvicorn app.main:app --reload
```

The local health endpoint is `http://127.0.0.1:8000/health` and returns:

```json
{"status":"ok"}
```

## Extension

The default development API origin is `http://localhost:8000`.

```bash
cd extension
npm install
npm run lint
npm run test -- --run
npm run build
```

Build against another API origin with:

```bash
VITE_API_ORIGIN=https://api.example.com npm run build
```

Load `extension/dist` as an unpacked extension in Chrome or Edge. The package
requests `storage`, access to Bilibili pages, and access to the configured API
origin.

## Docker

Container development is introduced in Task 13. Task 1 contains no Docker
runtime or production deployment configuration.
