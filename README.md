# 🔍 Debug Pipeline

**Automated backend error triage.** Debug Pipeline watches your logs, uses an LLM to trace each error back to the functions in your codebase that most likely caused it, and files a JIRA ticket with the root cause, debugging steps and fixes already written, so nobody has to triage it by hand.

![Overview dashboard](docs/overview.png)

## How it works

```mermaid
flowchart LR
    A["📦 Index your code<br/>(once)"] --> B["📡 Monitor<br/>log file or health URL"]
    B -->|error detected| C["🧠 Step 1<br/>find suspect functions"]
    C --> D["🧠 Step 2<br/>root cause from their real source"]
    D --> E["🎫 JIRA ticket<br/>fully triaged"]
    D --> F["📋 Dashboard"]
```

1. **Index.** Your backend source is parsed into a function-level index (name, docstring, source, API routes). Python, JavaScript/TypeScript, Java and Go are supported.
2. **Monitor.** A JSON log file is tailed for `ERROR` / `CRITICAL` / `FATAL` lines, or a health-check URL is polled and raises an event after repeated failures.
3. **Analyze in two LLM steps** (Groq, `openai/gpt-oss-120b`):
   - **Identify:** the error plus the function *index* goes to the LLM, which names the most likely culprits.
   - **Analyze:** the *actual source* of those functions goes back for a full diagnosis covering root cause, technical explanation, debugging steps, fixes, severity, confidence and affected components.
4. **Report.** A JIRA ticket is created with the whole analysis in its description, plus a plain-text backup comment.

## Dashboard

The Streamlit dashboard (`frontend/streamlit_app.py`) talks to the FastAPI backend over HTTP.

| Page | What it's for |
|---|---|
| 🏠 **Overview** | Pipeline status (index → monitor → AI → JIRA), incident KPIs, severity breakdown, latest incidents |
| 📡 **Live Monitor** | Start/stop log or health-check monitoring; live incident feed that refreshes every 4 s |
| 📋 **Incidents** | Filter by severity, search, then open any incident to see its fixes, debugging steps, explanation, suspected functions and raw log; links straight to its JIRA ticket |
| 📦 **Codebase** | Build the index from a ZIP upload or a folder; searchable browser of every indexed function |
| 🧪 **Test Logs** | Generate realistic fake logs with injected errors to try the pipeline end to end |
| ⚙️ **Settings** | Check the API, Groq key and JIRA connection (lists your project's issue types and priorities) |

![Incidents page](docs/incidents.png)

## Quick start

**Requirements:** Python 3.10+, a free [Groq API key](https://console.groq.com/keys), and optionally a free [JIRA Cloud](https://www.atlassian.com/software/jira/free) site.

```bash
git clone https://github.com/Nishikant090/debug-pipeline.git
cd debug-pipeline
python -m venv venv
venv\Scripts\activate          # Windows  (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env
```

Fill in `.env` (see [Configuration](#configuration)), then start the two processes in separate terminals:

```bash
uvicorn app.main:app --port 8088              # backend API  → http://127.0.0.1:8088/docs
streamlit run frontend/streamlit_app.py       # dashboard    → http://localhost:8501
```

### Try it in 2 minutes

1. **Codebase** → *Folder on the API server* → enter the absolute path of your backend (or this repo's `app/` folder) → **Build index**.
2. **Test Logs** → **Generate** (50 lines, 15% errors) → **Monitor it**.
3. **Start monitor**, then watch incidents appear on **Live Monitor** (about 10–30 s each) and open them on **Incidents**.

> **Tip:** Step 1 can only point at real functions if you index the code that *produced* the logs. With an unrelated index, the analysis falls back to reasoning from the log text alone, and the *Suspected functions* tab says so.

## Configuration

All settings live in `.env` (template: [`.env.example`](.env.example)). Restart the API after changing them.

| Variable | Required | Where to get it |
|---|---|---|
| `GROQ_API_KEY` | ✅ | [console.groq.com/keys](https://console.groq.com/keys) |
| `JIRA_BASE_URL` | for tickets | Your site, e.g. `https://yourname.atlassian.net` (from the browser address bar, without `/jira/...`) |
| `JIRA_EMAIL` | for tickets | The email you log in to Atlassian with |
| `JIRA_API_TOKEN` | for tickets | [id.atlassian.com → API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `JIRA_PROJECT_KEY` | for tickets | Ticket prefix, e.g. `KAN` for `KAN-1` (also in the board URL after `/projects/`) |
| `SMTP_USERNAME`, `SMTP_APP_PASSWORD`, `NOTIFY_EMAIL` | optional | Gmail + [App Password](https://myaccount.google.com/apppasswords); used by `demo_app.py` to email you when a ticket is created |
| `DEBUG_PIPELINE_API` | optional | Dashboard → API address if the API isn't on `http://127.0.0.1:8088` |

Use **Settings → Test JIRA connection** to verify the credentials. Tickets are created as `Bug`, falling back to `Task` if the project has no `Bug` type. If JIRA rejects a field, the client retries with fewer fields instead of failing.

## Deploy on Render

The repo includes a [`render.yaml`](render.yaml) Blueprint. It runs one free web service that starts the API privately on `127.0.0.1:8088` and serves the dashboard on the public URL ([`render_start.sh`](render_start.sh)).

1. On [Render](https://dashboard.render.com), choose **New → Blueprint** and connect this GitHub repo.
2. Fill in the secrets Render asks for: `GROQ_API_KEY`, plus the four `JIRA_*` values to create tickets.
3. Click **Apply**. The first build takes a few minutes.

On the free plan, the service sleeps after 15 minutes without traffic, and the next visit takes about a minute to wake it. The disk is reset on every restart, so incidents are cleared and the repo's own `app/` folder is re-indexed automatically. If the URL is public, anyone can use the dashboard, which spends your Groq quota and creates tickets in your JIRA project.

## Standalone demo (no backend)

[`demo_app.py`](demo_app.py) is a self-contained Streamlit app that calls the indexer and analyzer in-process. It needs no FastAPI server, so it can be deployed as-is on Streamlit Community Cloud. One click indexes this repo's `app/` folder, and you then pick a sample error (or paste your own JSON log line) to run the real pipeline.

```bash
streamlit run demo_app.py
```

Visitors can enter **their own** JIRA credentials in the sidebar (kept for the session only, never stored) to turn an analysis into a ticket in their own project. When deploying on Streamlit Cloud, add `GROQ_API_KEY` (and optionally the SMTP variables) under the app's **Secrets**.

## Log format

One JSON object per line. `level` and `message` (or `msg`) are used; every other field is passed to the LLM as context:

```json
{"timestamp": "2026-05-19T10:02:33Z", "level": "ERROR", "message": "AttributeError: 'NoneType' object has no attribute 'email'", "service": "auth-service", "traceback": "File \"app/services/auth_service.py\", line 42, in login_user ..."}
```

Generate test logs from the terminal:

```bash
python log_generator/fake_log_generator.py --output test_logs/live.log --count 200 --error-rate 0.2   # batch
python log_generator/fake_log_generator.py --output test_logs/live.log --interval 1.0                  # live stream
```

## API reference

Interactive docs: `http://127.0.0.1:8088/docs`

| Endpoint | Description |
|---|---|
| `POST /api/v1/index/upload` | Upload a ZIP of your backend and build the index |
| `POST /api/v1/index/path?directory=…` | Index a folder on the API server |
| `GET /api/v1/index/status` | Current index status |
| `POST /api/v1/monitor/start` | Start watching a log file (`{"log_path": …}`) or a URL (`{"monitor_type": "health", "health_url": …}`) |
| `POST /api/v1/monitor/stop` | Stop the active monitor |
| `GET /api/v1/monitor/status` | Monitor status and counters |
| `GET /api/v1/monitor/debug` | Detailed pipeline diagnostics (queue, Groq key check, last error) |
| `GET /api/v1/monitor/events` | Analysed incidents, newest first |
| `GET /api/v1/monitor/events/{id}` | One incident |
| `DELETE /api/v1/monitor/events` | Clear stored incidents |
| `GET /api/v1/monitor/jira-test` | Verify JIRA credentials; list issue types and priorities |
| `GET /health` | Service health |

## Robustness

- **Non-blocking pipeline.** Errors are analysed as background tasks, one LLM call at a time (semaphore), so the log watcher never stalls and Groq rate limits are respected. Transient Groq failures (rate limit, connection, 5xx) are retried with backoff.
- **Safe ZIP upload.** Every archive member is checked against "Zip Slip" path traversal, with caps on entry count, decompressed size and upload size.
- **Bounded LLM input.** Oversized function bodies and log entries are truncated before they reach the model.
- **Bounded indexing.** At most 8,000 files are indexed, so pointing at a huge directory can't hang the server.
- **Validated input.** Monitor parameters are bounds-checked (`422` on bad values), and `demo_app.py` rejects empty, invalid or non-object JSON with a clear message.

## Known limitations

- Incidents are kept **in memory** and are lost when the API restarts. The code index is persisted to `backend_index.json`.
- **No de-duplication yet:** the same error appearing twice is analysed twice and produces two tickets.
- JIRA priority is mapped from severity only on `Bug` tickets. The `Task` fallback (used when a project has no `Bug` type, as in default Kanban projects) omits priority, so those tickets get the project's default priority. Severity is still in the ticket title and description.

## Project structure

```
app/
├── analyzer/two_step_analyzer.py   # Two-step LLM analysis (identify → analyze)
├── indexer/                        # Index builder + parsers for Python, JS/TS, Java, Go
├── jira/client.py                  # JIRA ticket creation with field/issue-type fallbacks
├── monitor/log_watcher.py          # JSON log tailing
├── notifier/email_notifier.py      # Gmail SMTP owner notification
├── routers/                        # FastAPI endpoints (index, monitor)
├── config.py                       # Settings loaded from .env
├── models.py                       # Pydantic models (index, events, analysis, tickets)
├── state.py                        # In-memory shared state
└── main.py                         # FastAPI entrypoint
frontend/streamlit_app.py           # Dashboard (talks to the API over HTTP)
demo_app.py                         # Standalone demo, no backend needed
log_generator/fake_log_generator.py # Realistic fake JSON logs for testing
sample_logs/app.log                 # Small sample log (3 errors)
docs/                               # README screenshots
```

## Tech stack

Python · FastAPI · Groq (`openai/gpt-oss-120b`) · JIRA Cloud REST API v3 · Streamlit · Pydantic
