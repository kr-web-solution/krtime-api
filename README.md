# KRTime API

FastAPI backend for KRTime attendance: auth, locations, employees, devices, GPS + QR + face check-in, shifts, leave, corrections, reviews, and reports.

- **Stack**: Python 3.12, FastAPI, SQLAlchemy, Alembic, Postgres (`psycopg`), OpenCV / ONNX (YuNet + SFace)
- **Local port**: `8010` (Docker / Dokploy: `8000`)

## Environment

| File | Use |
| --- | --- |
| `.env` | Local development |
| `.env.production` | Dokploy / production |
| `.env.example` | Template (safe to commit) |

```bash
cp .env.example .env
# Set at least: DATABASE_URL, JWT_SECRET, EMBEDDING_ENCRYPTION_KEY
```

Required keys: `DATABASE_URL` (must use `postgresql+psycopg://`, **not** asyncpg), `JWT_SECRET`.  
When `APP_ENV=production`, `EMBEDDING_ENCRYPTION_KEY` is required.

The app also loads `.env` from the monorepo root if present.

## Local setup

```bash
cd krtime-api
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
```

| URL | Purpose |
| --- | --- |
| http://localhost:8010 | API |
| http://localhost:8010/docs | OpenAPI |
| http://localhost:8010/health | Health check |

Bootstrap admin (change immediately):

- Email: `admin@example.com`
- Password: `ChangeMeNow!Admin1`

## Face models

```bash
python scripts/download_face_models.py
```

| Env | Meaning |
| --- | --- |
| `FACE_ENFORCEMENT=required` | Face required for check-in |
| `FACE_ENFORCEMENT=optional` | Face preferred; may fall back |
| `FACE_ENFORCEMENT=off` | Skip face (labs / no weights) |

Weights land in `app/ml/weights/` (gitignored `.onnx` / `.bin`).

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
# DATABASE_URL must point at a reachable Postgres
pytest -q
```

Windows example:

```bash
set DATABASE_URL=postgresql+psycopg://user:pass@host:5432/attendguard
pytest -q
```

## Migrations

```bash
alembic upgrade head
```

On the Docker image, `scripts/entrypoint.sh` runs migrations before Uvicorn.

## Docker / Dokploy

```bash
# Build context = this folder
docker build -t krtime-api .
```

| Setting | Value |
| --- | --- |
| Dockerfile | `krtime-api/Dockerfile` |
| Context | `krtime-api/` |
| Port | `8000` |
| Health | `GET /health` |

Paste keys from `.env.production` into Dokploy → API environment.

See [docs/DOKPLOY_DEPLOY.md](../docs/DOKPLOY_DEPLOY.md).

## Main route groups

| Prefix / area | Responsibility |
| --- | --- |
| `/auth` | Login, refresh cookie, logout |
| `/employees`, `/devices`, `/locations` | Admin CRUD |
| `/attendance` | Check-in/out, today status, presence |
| `/biometrics` | Face enroll / verify |
| `/qr` | Rotating site QR |
| `/shifts`, `/leave`, `/holidays` | Scheduling |
| `/corrections`, `/reviews` | Manual fixes / face reviews |
| `/reports`, `/admin` | Dashboards & exports |
| `/security-events` | Geofence exit & fraud signals |

## Optional integrations

| Service | Env prefix | Role |
| --- | --- | --- |
| ntfy | `NTFY_*` | Push to admin / employees |
| S3 / MinIO | `S3_*` | Backup object storage |

Leave blank to disable.

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/download_face_models.py` | Fetch YuNet + SFace weights |
| `scripts/measure_face_scores.py` | Tune match threshold |
| `scripts/load_test_checkins.py` | Load-test check-ins |
| `scripts/entrypoint.sh` | Container start (migrate + serve) |
