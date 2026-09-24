# SIH 2026 Submission Monitor

Full-stack dashboard for SIH 2026 submission counts.

**Official source:** https://www.sih.gov.in/sih2026PS

## Architecture

- React + Vite frontend
- FastAPI backend
- Neon PostgreSQL database
- Official SIH problem-statement page as the data source
- Five-minute polling by default
- Separate Software and Hardware rankings
- Historical submission snapshots are stored only when a count changes
- No prediction engine is included

## 1. Neon setup

Create a Neon PostgreSQL project and copy its pooled connection string. Neon connection strings use PostgreSQL format and include `sslmode=require`. Keep the URL secret and never commit it to Git.

Set:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require'
```

For local development, you can copy `backend/.env.example` to `.env` and export/load the variables with your preferred environment-variable tool.

## 2. Run backend locally

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require'
export CORS_ORIGINS='http://localhost:5173'
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs`.

## 3. Run frontend locally

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:5173`.

## 4. Manual sync

```bash
curl -X POST http://localhost:8000/api/sync
```

## 5. Production deployment

### Neon
Create the database and copy the pooled PostgreSQL connection string.

### Render
This repository includes `render.yaml`.

Backend settings:

- Root directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `DATABASE_URL`: Neon connection string
- `CORS_ORIGINS`: your Vercel frontend URL
- `SIH_SYNC_MINUTES`: `5`

### Vercel
Import the repository and set the frontend root directory to `frontend`.

Set:

```text
VITE_API_URL=https://YOUR-RENDER-SERVICE.onrender.com
```

Redeploy after setting the environment variable.

## Data accuracy safeguards

The scraper identifies the SIH table by its column headers instead of assuming fixed column positions. It validates PS IDs, categories, submission counts, capacities, and duplicate PS numbers before publishing a sync. If a fetch or validation fails, the API marks the dataset as stale instead of replacing good data with an invalid snapshot.

## Important operational note

The backend currently performs polling in its web-service process. If the hosting provider suspends an idle service, polling will pause. For uninterrupted collection, use a continuously running service or move the sync job to a scheduled worker/cron service later.

The project does not bypass authentication, CAPTCHAs, rate limits, or other access controls.
# Submission_Monitor_SIH26
