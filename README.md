# JB APUL v3 — YouTube Automation Platform

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js (React) + Tailwind CSS |
| Backend | FastAPI (Python 3.12) |
| Database | PostgreSQL 16 |
| Cache/Queue | Redis 7 |
| Workers | Python (FFmpeg) |
| Deployment | Docker Compose |

## Quick Start

```bash
# 1. Clone repo
git clone <repo-url> && cd jb_apulv3

# 2. Setup
./scripts/setup.sh

# 3. Open browser
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| frontend | 3000 | Next.js app |
| backend | 8000 | FastAPI API |
| db | 5432 | PostgreSQL |
| redis | 6379 | Redis cache/queue |
| nginx | 80 | Reverse proxy |

## Features

- **Dashboard** — Channel overview, stats, quick actions
- **Media Library** — Upload/manage video, audio, thumbnails
- **Production** — Video assembly (FFmpeg)
- **Upload** — YouTube upload via Data API
- **Livestream** — 24/7 livestream via FFmpeg
- **Pipeline** — Automated produce → upload → live cycle

## Development

```bash
# View logs
docker-compose logs -f backend

# Access backend shell
docker-compose exec backend bash

# Access database
docker-compose exec db psql -U jb_user jb_apulv3

# Run migrations
docker-compose exec backend alembic upgrade head
```

## Migrate to New VPS

```bash
# 1. Install Docker on new VPS
curl -fsSL https://get.docker.com | sh

# 2. Clone repo
git clone <repo-url> && cd jb_apulv3

# 3. Copy env
cp .env.example .env
# Edit .env with new credentials

# 4. Setup
./scripts/setup.sh

# 5. Done!
```

## Project Structure

```
jb_apulv3/
├── backend/           # FastAPI application
│   ├── app/
│   │   ├── api/       # API routes
│   │   ├── core/      # Config, auth
│   │   ├── db/        # Database session
│   │   ├── models/    # SQLAlchemy models
│   │   └── services/  # Business logic
│   └── Dockerfile
├── frontend/          # Next.js application
├── workers/           # Python workers
│   ├── production/    # Video production
│   └── livestream/    # Livestream engine
├── nginx/             # Nginx config
├── scripts/           # Setup scripts
├── docker-compose.yml # Docker services
└── .env.example       # Environment template
```
