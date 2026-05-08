# BookBrief AI

AI-powered book summaries: paste text, upload PDF, or describe a title—get polished summaries in multiple styles, with Stripe subscriptions and a vanilla JS + Tailwind frontend.

## Project layout

```
bookbrief-ai/
├── backend/           # FastAPI app
├── frontend/          # Static HTML + JS
├── static/            # Shared CSS / built assets
└── README.md
```

## Quick start (development)

1. Create a virtual environment (Python 3.12) and install dependencies:

```bash
cd bookbrief-ai/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copy environment file and adjust secrets:

```bash
cp .env.example .env
```

3. Run the API (serves `/health`, `/frontend/*`, `/static/*`, redirects `/` to the landing page):

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Audiobook, Podcast, and Video Summary

These features run from the **summary detail** page (`/frontend/summary-view.html`):

| Feature | What it uses | Notes |
|--------|----------------|-------|
| **Audiobook** | `POST /api/v1/audio/narrate` + poll | Async jobs are stored in **`audio_tts_jobs`** so polling works with **multiple uvicorn workers** (e.g. Render’s `--workers 2`). |
| **Podcast** | `POST /api/v1/audio/podcast-script` (GPT), then same `/audio/narrate` per segment | Script generation needs **`OPENAI_API_KEY`**. Optional **`MANUS_API_KEY`** switches narration to Manus tasks (with OpenAI fallback if Manus fails). |
| **Video summary** | Manus task API via `POST /api/v1/summaries/{id}/video-summary` | Requires **`MANUS_API_KEY`** (and optional **`MANUS_API_BASE`**). |

Always run **`alembic upgrade head`** after pulling so tables such as `audio_tts_jobs` exist.

## Database

- **Development:** set `DATABASE_URL=sqlite:///./bookbrief.db` (default in `.env.example`).
- **Production:** set `DATABASE_URL` to a PostgreSQL URL using `postgresql+psycopg2://...`.
- After pulling code that changes models or adds migrations, run **`alembic upgrade head`** from `backend/` before starting the app (otherwise you may see errors like `no such column`).

Migrations (after models exist in step 2):

```bash
cd backend
alembic revision --autogenerate -m "message"
alembic upgrade head
```

## Implementation checklist

1. **Project setup** — backend skeleton, config, DB session, Alembic, static mounts *(this step)*  
2. Database models  
3. Authentication  
4. Landing + Tailwind  
5. Stripe  
6. LangGraph summarization  
7. API routes  
8. Frontend pages  
9. Render deployment  

### Render (production)

The app is one **web service** (FastAPI + static `frontend/` and `static/`) plus **Render Postgres**. Use `render.yaml` in this directory when the **git repository root** is `bookbrief-ai/`.

If the app lives in a **subfolder** of the repo (e.g. `BookBrief/bookbrief-ai/`), copy `render.yaml` to the repository root and set `rootDir: bookbrief-ai` (instead of `rootDir: .`).

1. Push the repo to GitHub/GitLab/Bitbucket.
2. In [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**, connect the repo and apply the matching `render.yaml`.
3. When prompted for **sync: false** variables, set at least:
   - **OPENAI_API_KEY** — required for summarization.
   - **CORS_ORIGINS** — comma-separated allowed browser origins. After the first deploy, set this to your public URL (same value as **Environment → `RENDER_EXTERNAL_URL`**, e.g. `https://bookbrief-web.onrender.com`). Same-origin requests to the app URL work without extra origins, but set this if you open the API from other sites or tools.
   - **Stripe** — `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_UNLIMITED` for billing (optional until you test Checkout).
4. **Stripe webhook** — in Stripe Dashboard, endpoint `https://<your-service>.onrender.com/stripe/webhook`, events for subscription lifecycle; use the signing secret as `STRIPE_WEBHOOK_SECRET`.
5. **Migrations** run on each deploy via `alembic upgrade head` in the start command.

Render sets **`RENDER_EXTERNAL_URL`** automatically. If you do not set **`PUBLIC_APP_URL`**, the API uses that value for Stripe return URLs and the billing portal (see `resolved_public_origin` in config). Override **`PUBLIC_APP_URL`** when you add a custom domain.

Optional: [Render CLI](https://render.com/docs/cli) — `render blueprints validate` from the directory that contains `render.yaml`.

## License

Proprietary / your choice — set before publishing.
