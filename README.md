# Autonomous AI Agent System for HR — Resume Screening & Interview Scheduling

**Google Forms → Sheets polling → resume parse → Groq LLM scoring → Google Calendar + Meet invites**

An agentic HR pipeline: HR connects a Google Form; new submissions trigger automatic resume download, intelligent scoring against the job description (with keyword fallback), and—when the candidate passes your threshold—automatic scheduling on **your** Google Calendar with **Google Meet** and email invites to the candidate.

## Architecture

```
  Google Form (applications)
           │
           ▼
  Linked Sheet ──poll──► Form watcher (Drive API: resume files)
           │
           ▼
  Parse PDF/DOCX ──► Score vs job description
           │              │
           │        Groq LLM (role-fit)
           │        or keyword fallback
           ▼
  Score ≥ threshold? ──yes──► Free/busy + create Calendar event + Meet link
           │                      │
           no                     └──► Candidate receives invite email
           ▼
  Results JSON in backend/upload_results/
```

## Features

- **Google Forms integration** — paste a form URL; the service polls the linked spreadsheet for new rows and pulls resume attachments from Drive.
- **Resume parsing** — PDF and Word text extraction for structured scoring.
- **AI screening** — **Groq** (`llama-3.3-70b-versatile`) scores fit to the role from your job description; without `GROQ_API_KEY`, a **keyword fallback** runs automatically.
- **Configurable thresholds** — per-job score cutoff (0–100) and optional keywords.
- **Interview scheduling** — uses **Google Calendar** free/busy, creates events with **Google Meet**, emails the candidate (form must collect email — e.g. question titled **Email** or **Email address**).
- **Reschedule flow** — API to **check interview responses** when candidate or interviewer declines so you can trigger a new slot (see Swagger `/docs`).
- **FastAPI backend** — interactive **OpenAPI docs** at `/docs`; optional **React + Vite** frontend under `frontend/`.

## Prerequisites

1. **Google Cloud project** with OAuth **Desktop** client → download as `backend/credentials.json`.
2. Enable APIs: **Google Sheets**, **Google Drive**, **Google Forms**, **Google Calendar** (see `backend/CALENDAR_SETUP.txt` for Calendar scopes and token refresh).
3. **Groq API key** (optional but recommended): [Groq Console](https://console.groq.com) → set `GROQ_API_KEY` in `backend/.env`.

## Setup

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env` (never commit):

```env
GROQ_API_KEY=your_groq_key_here
```

Place `credentials.json` in `backend/`. On first run, OAuth opens in the browser → **`token.json`** is created (gitignored).

### 2. Run the API

From the repository root:

```powershell
.\run_backend.bat
```

Or manually:

```powershell
cd backend
python main.py
```

- **App / UI:** [http://localhost:8000](http://localhost:8000)  
- **Swagger:** [http://localhost:8000/docs](http://localhost:8000/docs)  
- **Health:** `GET /health`

The bundled `run_backend.bat` uses **Python 3.10** (`py -3.10`). Adjust if your machine uses another version.

### 3. Frontend (optional — Vite + React)

```powershell
cd frontend
npm install
npm run dev
```

Point the UI at your backend URL if it differs from the default (see `vite.config.js` / env if configured).

## Using the Forms API (high level)

1. Configure a job (description, threshold, optional interviewer email) via the watch endpoint — see **`POST /api/forms/watch`** in `/docs`.
2. The watcher polls on an interval (e.g. every **60** seconds).
3. Each new row saves resumes under `backend/uploads/` and writes scoring output under `backend/upload_results/` (`*_result.json`), including scheduled event links when applicable.

## Environment variables

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Enables LLM-based resume scoring via Groq. If unset, keyword fallback is used when possible. |

Google OAuth secrets stay in **`credentials.json`** and **`token.json`** (local only).

## Project structure

```
Autonomous-AI-Agent-System-for-HR-Resume-Screening-and-Interview-Scheduling/
├── README.md
├── run_backend.bat          # Windows: install deps + start FastAPI
├── backend/
│   ├── main.py              # FastAPI app
│   ├── api_forms.py         # Forms API routes
│   ├── form_watcher.py      # Sheets/Drive/Forms polling & OAuth
│   ├── resume_parser.py
│   ├── llm_scorer.py        # Groq scoring + fallback
│   ├── calendar_scheduler.py
│   ├── CALENDAR_SETUP.txt   # Calendar API & scopes checklist
│   ├── static/              # Served UI (fallback)
│   ├── uploads/             # Downloaded resumes (local)
│   └── upload_results/      # Parse/score JSON outputs (local)
└── frontend/                # React + Vite HR dashboard (optional)
```

## Security

- Keep **`.env`**, **`credentials.json`**, and **`token.json`** out of version control (see `.gitignore`).
- Treat **`upload_results/`** and **`uploads/`** as sensitive HR data; do not commit candidate files.

## Repository

This project lives on GitHub: [HeshikaVarthini/Autonomous-AI-Agent-System-for-HR-Resume-Screening-and-Interview-Scheduling](https://github.com/HeshikaVarthini/Autonomous-AI-Agent-System-for-HR-Resume-Screening-and-Interview-Scheduling).
