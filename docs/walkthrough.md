# FinancialMarketReport — Outside-In Deep Dive

A teaching-grade walkthrough of `/home/josej/Projects/FinancialMarketReport`, written
so that by the end you could rebuild a similar Flask web app from scratch. Goes from
the outside (how a browser request reaches the code) inward to the deepest modules.

---

## Part 0 — The mental model before we start

A web app is a **long-running process listening on a TCP port** that, when an HTTP
request arrives, runs some code and writes an HTTP response back. Everything else is
decoration:

- **Docker** decides which OS the process sees and which TCP ports the host forwards to it.
- **Flask** is the Python library that turns "an HTTP request arrived on socket X" into
  "call this function with these arguments, then send its return value back as an HTTP response."
- **Jinja2** is a string-templating library that takes an HTML file with `{{ placeholders }}`
  and produces a finished HTML string.
- **CSS** is a separate file the browser downloads after the HTML and uses to apply visual styling.
- **SQLite** is a single-file database the process reads/writes directly (no separate database server).
- **Background threads** are how the same process can also run periodic work (the scheduler)
  and slow work (a report run triggered from a button click) without blocking the HTTP socket.

The "site" is just: `process running` × `TCP port open` × `routing logic` × `HTML/CSS the
browser renders`. Once you internalize that, the rest is naming things.

---

## Layer 1 — How a browser request physically reaches your Python code

Pretend you type `http://10.5.251.8:8082/` into your browser. The chain, every hop:

1. **Browser parses the URL.** Scheme `http`, host `10.5.251.8`, port `8082`, path `/`.
2. **TCP connection** to `10.5.251.8:8082`. On the QNAP this lands on the Docker daemon's
   port-publishing rules. On a dev laptop the equivalent is `127.0.0.1:8080` because
   `docker-compose.yml` declares `"8080:8080"` (host:container). On the NAS that mapping is `8082:8080`.
3. **Docker forwards** the connection to port 8080 *inside* the `financial-market-report`
   container, where Flask's dev server has a listening socket bound to `0.0.0.0:8080`
   (`--host 0.0.0.0` in the Dockerfile CMD means "listen on all interfaces inside the
   container," not just loopback).
4. **HTTP request** is sent over that connection: `GET / HTTP/1.1\r\nHost: ...\r\n\r\n`.
5. **Werkzeug** (Flask's underlying HTTP server library) parses those bytes into a `Request` object.
6. **WSGI dispatch.** Werkzeug calls a Python function with two arguments — `(environ, start_response)`.
   That function is the Flask `app` object. Flask routes the request to the function defined with
   `@app.get("/")` (the `dashboard` view in `web/app.py`).
7. **Your handler runs.** It reads the DB, picks a template, calls `render_template("dashboard.html", ...)`,
   which produces an HTML string.
8. **Flask wraps it in a `Response`** with status 200 and `Content-Type: text/html`.
9. **Werkzeug serializes** that back to HTTP bytes and writes them down the socket.
10. **Browser receives HTML**, parses it, sees `<link rel="stylesheet" href="/static/app.css">`,
    opens another connection (or reuses the first) to fetch `/static/app.css`, then renders.

Two things worth tattooing in:

- **WSGI** is the contract between the HTTP server and your Python app. It is *just a function
  signature*. Any WSGI-compliant server (gunicorn, uWSGI, waitress, the dev server) can run any
  WSGI-compliant app. This is why Flask doesn't ship its own production server: it expects you to
  put one in front in production.
- **Routing is a dictionary lookup.** Flask keeps an internal `URL Map` of `(method, path pattern) → function`.
  The `@app.get` decorator literally calls `app.add_url_rule(...)` to insert into that map. No magic.

The smallest possible Flask program:

```python
from flask import Flask
app = Flask(__name__)

@app.get("/")
def home():
    return "<h1>Hello</h1>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

Five lines. Everything else in this project is added structure for testability, configurability,
persistence, deployment.

---

## Layer 2 — The container that wraps the process

### 2.1 The Dockerfile, line by line

```dockerfile
FROM python:3.12-slim
```
The base image. `python:3.12` is Debian + Python; `-slim` strips man pages, locales, etc.
(~50 MB vs ~350 MB). For pure-Python apps that don't need to compile C extensions at install
time, slim is the right default.

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV FINANCIAL_MARKET_REPORT_HOME=/app
```
Four classic container env vars:
- `PYTHONDONTWRITEBYTECODE=1` — don't create `.pyc` files. Useless in an immutable container;
  they just bloat layers and confuse file watches.
- `PYTHONUNBUFFERED=1` — flush `print()` immediately. Without this, `docker logs` can be silent
  for minutes because Python buffers when stdout isn't a TTY.
- `PIP_NO_CACHE_DIR=1` — don't keep the wheel cache after install. Saves hundreds of MB.
- `FINANCIAL_MARKET_REPORT_HOME=/app` — app-specific. Read by `config.py:_project_root()` to
  anchor file paths inside the container.

```dockerfile
WORKDIR /app

COPY pyproject.toml README.md ./
COPY config ./config
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install .
```
The COPY+install dance is the standard Python container pattern. Notice what's *not* copied:
`data/`, `reports/`, `logs/`, `secrets/`, `.git/`, the notebook, tests. `.dockerignore` enforces
this. Smaller image, no secrets accidentally baked in. `pip install .` installs the package using
`pyproject.toml` and registers the `financial-market-report` console script.

```dockerfile
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data /app/reports /app/logs /run/secrets \
    && chown -R appuser:appuser /app /run/secrets

USER appuser
```
**Never run a container as root** unless you have a reason. If an attacker gets RCE in the Python
process, they're confined to a UID that owns nothing important. UID 1000 is the conventional first
non-root UID on Linux; matching it means bind-mounted files from the host show up with sensible
ownership.

```dockerfile
EXPOSE 8080
CMD ["financial-market-report", "serve", "--host", "0.0.0.0", "--port", "8080"]
```
`EXPOSE` is metadata — it doesn't actually publish a port; that's compose's job. `CMD` in JSON-array
form runs the binary directly (no shell), so signals (`SIGTERM` on `docker stop`) reach Python
directly and the `try/finally` in `run_dev_server` actually executes the scheduler shutdown.

Decisions worth absorbing:
- Multi-stage builds shrink images but only matter if you compile C extensions. Single stage is right here.
- COPY order matters for layer caching: copy `pyproject.toml` *before* `src/` to cache the dep
  install across most code changes. This Dockerfile copies them together — a small efficiency miss,
  irrelevant at this scale.
- `python:3.12-alpine` would be smaller but Alpine uses musl libc, which breaks pre-built Python
  wheels for pandas/numpy/matplotlib. **Don't use Alpine for data-science Python.**

### 2.2 docker-compose.yml, line by line

```yaml
services:
  financial-market-report:
    build: .
    image: financial-market-report:local
    container_name: financial-market-report
    restart: unless-stopped
    user: "${FMR_UID:-1000}:${FMR_GID:-1000}"
```
`build: .` → build from the Dockerfile here. `image:` names the result for reuse. `restart: unless-stopped`
means Docker brings it back after a crash or host reboot but won't fight you when you `docker compose stop`.
`user:` overrides the in-image USER; `${VAR:-default}` is shell-style fallback.

```yaml
    ports:
      - "8080:8080"
```
**HOST:CONTAINER**. The bit you'd change to `8082:8080` on the NAS to move the public port without
touching the app.

```yaml
    environment:
      FINANCIAL_MARKET_REPORT_HOME: /app
      APP_SECRETS_DIR: /run/secrets
      VAULT_ADDR: ${VAULT_ADDR:-http://vault:8200}
      VAULT_TOKEN: ${VAULT_TOKEN:-}
      VAULT_SECRET_PATH: ${VAULT_SECRET_PATH:-secret/data/financial-market-report}
      ...
```
Every key becomes an env var inside the container. `${X:-default}` first checks the host shell /
`.env`. So secrets like `VAULT_TOKEN` come from your *uncommitted* `.env`, never from the YAML.

```yaml
    volumes:
      - ./data:/app/data
      - ./reports:/app/reports
      - ./logs:/app/logs
      - ./secrets:/run/secrets:ro
```
Bind mounts: `host_path:container_path[:mode]`. First three read-write — SQLite DB and reports
survive container replacement. Fourth is **read-only** (`:ro`). Principle: state lives outside the
container, code lives inside.

```yaml
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/', timeout=5).read()"]
      interval: 1m
      timeout: 10s
      retries: 3
```
Docker runs this every 60s inside the container. Three consecutive failures → unhealthy. `restart:
unless-stopped` does *not* restart on unhealthy alone — at minimum `docker ps` shows `(unhealthy)`.
Using `python -c` instead of `curl` is deliberate: `python:3.12-slim` doesn't ship curl.

```yaml
    networks:
      - homelab

networks:
  homelab:
    external: true
    name: ${HOMELAB_DOCKER_NETWORK:-homelab}
```
`external: true` → "I'm not creating this network; assume it exists." Created by `docker network
create homelab` (or the HomelabInfra repo's compose). Joining a shared network is what lets this
container reach `vault:8200` by Docker DNS.

---

## Layer 3 — Python packaging and the entry point

### 3.1 pyproject.toml

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"
```
Tells `pip install .` *how* to build. Required by PEP 517. `setuptools` is the default; alternatives
are `hatchling`, `poetry-core`, `flit-core`.

```toml
[project]
name = "financial-market-report"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "Flask>=3.1", "matplotlib>=3.10", "hvac>=2.3", "mplfinance>=0.12.10b0",
    "pandas>=2.2", "PyYAML>=6.0", "requests>=2.32", "yfinance>=0.2.66", ...
]
```
Modern Python: declare deps in `pyproject.toml`, **not** `requirements.txt`. The latter is for
reproducible env reproduction (a frozen lockfile); the former is for *what your package needs*.
The dual presence in this repo is messy — the `requirements.txt` is largely a notebook-era
leftover; the canonical list is here.

```toml
[project.scripts]
financial-market-report = "financial_market_report.cli:main"
```
The magic line. After `pip install .`, a shell shim called `financial-market-report` appears on
`PATH`. When invoked it does `from financial_market_report.cli import main; sys.exit(main())`.
That's how the Dockerfile CMD works.

```toml
[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
financial_market_report = ["web/templates/*.html", "web/static/*.css"]
```
`find` → "look in `src/` for packages." Without this the `src/` layout doesn't work. `package-data`
includes non-Python files (HTML, CSS) in the installed wheel — without it, templates wouldn't ship
and Flask would 500 in production.

### 3.2 The src/ layout — why?

Flat layout is dangerous: running `pytest` from the project root auto-adds `.` to `sys.path`, so
`import financial_market_report` finds the source dir whether or not the package is installed. Tests
can pass against an uninstalled package and fail in production where a missing `package-data`
declaration would have surfaced. The `src/` layout forces you to install the package (`pip install
-e .` for editable mode) before tests can find it. **Use `src/` for any new project.**

### 3.3 cli.py — argparse and lazy imports

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="financial-market-report")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Generate the market report")
    run_parser.add_argument("--no-email", dest="send_email", action="store_false")
    ...
```
`argparse` is stdlib. The `dest="send_email", action="store_false"` pattern makes `--no-X` flags
that default to "use the config value" (None) when unspecified. The runner then does
`if override is None: use config else: use override`.

Modules are imported **lazily**:
```python
if args.command == "run":
    from financial_market_report.runner import run_report
if args.command == "serve":
    from financial_market_report.web.app import run_dev_server
```
Why? `runner.py` transitively imports pandas, matplotlib, mplfinance — 1-2 seconds to load. A user
typing `--help` shouldn't pay for it. **For any multi-subcommand CLI, lazy-import inside each branch.**

---

## Layer 4 — The Flask application object

### 4.1 The application factory

```python
def create_app(*, db_path: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = "local-dev-change-me"
    app.config["DB_PATH"] = str(db_path or DEFAULT_DB_PATH)
    init_db(app.config["DB_PATH"])

    @app.get("/")
    def dashboard():
        ...
    ...
    return app
```
`Flask(__name__)` — the constructor wants the import name of the module the app lives in. Flask uses
it to find `templates/` and `static/` directories relative to that module. Because this file is
`financial_market_report.web.app`, Flask looks in `src/financial_market_report/web/templates/` and
`.../static/`. That's why those folders are nested next to the module — convention, not config.

`app.secret_key` is used to **sign the session cookie** (HMAC). Flask stores `flash()` messages in
the session, encoded into a cookie sent to the browser. The signature prevents the browser from
forging a fake session. `"local-dev-change-me"` is fine for a LAN dashboard with no real auth; do
not ship that publicly.

`app.config` is just a dict. By convention, settings go here so they can be overridden per-test.

**Why a factory at all?** Three reasons: (1) testability — each test creates a fresh app pointed at
a temp DB, no globals leak; (2) multiple instances in one process; (3) side-effect ordering — the
factory controls when `init_db()` runs and when the scheduler attaches. Module-level `app =
Flask(__name__)` would run those side effects on import, hostile to tests.

### 4.2 The serve wrapper

```python
def run_dev_server(*, host, port, db_path=None, debug=False,
                   enable_scheduler=True, scheduler_interval_seconds=60) -> None:
    app = create_app(db_path=db_path)
    scheduler = None
    if enable_scheduler:
        scheduler = ReportScheduler(db_path=app.config["DB_PATH"], ...)
        app.config["SCHEDULER"] = scheduler
        scheduler.start()
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    finally:
        if scheduler is not None:
            scheduler.stop()
```
`use_reloader=False` is critical with background threads. Flask's auto-reloader runs your app code
in *two* processes (parent watches files, child serves). The scheduler would start in both
(double-firing) or in the wrong one. Disabling the reloader sidesteps it, at the cost of manual
restart after code changes.

The `try/finally` ensures `scheduler.stop()` runs on `Ctrl+C` (which raises `KeyboardInterrupt`).

**Production note:** `app.run()` is the dev server. Real production: `gunicorn -w 1 -b 0.0.0.0:8080
'financial_market_report.web.app:create_app()'` with `-w 1` because the scheduler must not be
duplicated. This app's "production" is a homelab container; the dev server is "good enough."

---

## Layer 5 — Routing and the request lifecycle

### 5.1 What a route actually is

```python
@app.get("/")
def dashboard():
    latest_run = get_latest_report_run(app.config["DB_PATH"])
    ...
    return render_template("dashboard.html", latest_run=latest_run, ...)
```
The decorator is sugar for `app.add_url_rule("/", endpoint="dashboard", view_func=dashboard,
methods=["GET"])`. Three concepts: **Rule** = URL pattern; **Endpoint** = internal name (defaults
to function name) — what `url_for("dashboard")` looks up; **View function** = the callable. Flask
matches request method + path against its URL map. No match → 404. Method-mismatch → 405.

### 5.2 URL converters

```python
@app.get("/runs/<int:run_id>")
def run_detail(run_id: int):
    ...
```
`<int:run_id>` only matches digit sequences, passes as `int`. Converters: `string` (default, no
slashes), `int`, `float`, `path` (allows slashes), `uuid`.

The `report_asset` route uses both:
```python
@app.get("/reports/<int:run_id>/<path:filename>")
def report_asset(run_id: int, filename: str):
    requested = Path(filename)
    if requested.name != filename:
        abort(404)
    ...
```
`<path:filename>` allows slashes. The check `requested.name != filename` says "after PathLib parses
it, the basename must equal the original — no `/` and no `..`." That's a path-traversal guard.

### 5.3 The request and response objects

Flask sets a thread-local `request` object:
```python
from flask import request
@app.post("/settings")
def update_settings_view():
    for key, _label, field_type in SETTING_FIELDS:
        if field_type == "checkbox":
            values[key] = key in request.form          # bool
        elif field_type == "multicheckbox":
            values[key] = request.form.getlist(key)    # list[str]
        elif key in request.form:
            raw = request.form[key].strip()            # str
            ...
```
`request.form` is the parsed form body for `application/x-www-form-urlencoded` (what HTML forms POST
by default). It's a `MultiDict` — dict-like, allows multiple values per key (`getlist`).

What a view can return: a string (→ 200 text/html), a `Response`, a tuple `(body, status[, headers])`,
a `redirect(url_for(...))` (→ 302 with `Location`), the result of `render_template(...)` (a string),
the result of `send_file(path)`.

Helpers used here: `flash("msg")` (store one-shot text in session for the next request to display);
`abort(404)` (raise an HTTP exception); `redirect(url_for("runs"))` (POST-redirect-GET);
`send_file(path)` (stream a file from disk); `send_from_directory(dir, filename)` (same with built-in
traversal protection).

### 5.4 POST → Redirect → GET (PRG)

```python
@app.post("/runs")
def run_now():
    ...
    threading.Thread(target=target, daemon=True).start()
    flash("Report run started. Refresh run history to see progress.")
    return redirect(url_for("runs"))
```
After a successful POST, redirect to a GET URL rather than rendering directly. Why? If the user hits
Refresh on a POST response, the browser asks "Confirm form resubmission?" and could double-submit.
Redirecting to a GET makes Refresh idempotent. The flash message survives via the session cookie.
You'll see PRG in every form-handling route here: settings save, run trigger, delete, clear.

### 5.5 Walking each route

- **GET `/`** — `dashboard`: pure read; latest run + running run + 5 recent reports + scheduler status;
  renders `dashboard.html`. The `if scheduler else None` guard exists because tests may create the
  app without a scheduler.
- **GET `/runs`** — last 50 runs → `runs.html`.
- **GET `/runs/<int:run_id>`** — one run + its ticker candidates → `run_detail.html`; `abort(404)` if missing.
- **POST `/runs`** — `run_now`: spawns a daemon thread calling `run_report(...)`, returns "Started"
  + redirect. Button disabled in UI when a `running` row exists; server *also* re-checks
  (`if running_run is not None: flash(...)`) — never trust client-side state.
- **POST `/runs/<id>/delete`** — removes one row (refuses if `running`).
- **POST `/runs/clear`** — bulk-delete completed runs + reset the scheduler's "last run" memory.
- **GET `/reports`** — list reports → `reports.html`.
- **GET `/reports/<id>/open`** — `_resolve_report_path(...)` then `send_file(path)`; `abort(404)`
  if not found. `_resolve_report_path` handles "DB recorded a dev-machine path; container sees a
  different layout" by trying the stored path, then project root, then the substring after `reports/`.
- **GET `/reports/<id>/<path:filename>`** — streams a chart PNG next to the HTML; path-traversal guard.
- **GET `/settings`** — builds a list of `{key, label, type, value, options}` dicts the template
  iterates over. Declarative form rendering: adding a setting = "append to `SETTING_FIELDS`," not
  "edit two files."
- **POST `/settings`** — `update_settings_view`: symmetric inverse; for each declared field pull
  the right shape out of `request.form`, coerce to the right type, upsert into SQLite.
- **GET `/secrets`** — `secret_status(...)` shows `configured`/`missing` per secret without printing values.

### 5.6 What's missing (and you'd want for production)

- **Authentication** — anyone on the LAN can open it. Add Flask-Login or HTTP basic auth via a
  reverse proxy (nginx/Traefik) for any internet-facing deploy.
- **CSRF tokens** — Flask-WTF provides them. Without, any other site you visit could submit a form
  to your dashboard if you have it open. LAN-only mitigates; doesn't eliminate.
- **Rate limiting** — Flask-Limiter.
- **Structured logging** — the app uses `app.logger.exception(...)` in a couple places; production
  would configure JSON logs to a log aggregator.
- **Error pages** — Flask's default 404/500 pages are bare. Use `@app.errorhandler(404)` to render a templated page.

---

## Layer 6 — Templates (Jinja2) in detail

### 6.1 Why a templating language at all

You *could* return HTML by string concatenation (`return f"<h1>Hello {name}</h1>"`). Two problems:
**XSS** (if `name = '<script>alert(1)</script>'`, you just shipped JS to the browser) and
**maintainability** (real pages are 200+ lines). Jinja solves both: auto-escapes by default
(`<script>` → `&lt;script&gt;`) and separates HTML from Python.

### 6.2 Inheritance with `extends` and `block`

`base.html` is the layout:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Financial Market Report{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
</head>
<body>
  <header class="topbar">
    <a class="brand" href="{{ url_for('dashboard') }}">Financial Market Report</a>
    <nav>
      <a href="{{ url_for('dashboard') }}">Dashboard</a>
      <a href="{{ url_for('runs') }}">Runs</a>
      <a href="{{ url_for('reports') }}">Reports</a>
      <a href="{{ url_for('settings') }}">Settings</a>
      <a href="{{ url_for('secrets') }}">Secrets</a>
    </nav>
  </header>
  <main>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="messages">
          {% for message in messages %}
            <div class="message">{{ message }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```
Every page inherits this. `{% block title %}` and `{% block content %}` are named holes child
templates fill:
```html
{% extends "base.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
  <section>...</section>
{% endblock %}
```
The browser receives the *finished* HTML — Jinja runs entirely on the server. `{% with var = expr %}`
introduces a scoped variable. `get_flashed_messages()` is a Flask-provided template global that pops
the flash messages out of the session.

### 6.3 Two delimiter types

- `{{ expr }}` — print an expression's value, escaped.
- `{% stmt %}` — control flow: `if`/`elif`/`else`/`endif`; `for ... else ... endfor` (the `else`
  runs if the iterable was empty); `extends`; `include`; `block`; `set`; `macro` (template-level functions).

### 6.4 Filters

The pipe runs the left value through a filter:
```html
{{ "%.2f"|format(ticker.price or 0) }}
{{ ticker.company_name or "-" }}
```
`format` is the Python `%` formatter. `or "-"` uses Python's `or` (returns the first truthy operand).
Common built-ins: `length`, `upper`, `lower`, `default`, `join`, `safe`, `e` (force escape),
`tojson`.

### 6.5 Auto-escaping and the safe filter

By default Jinja escapes everything in `{{ ... }}` for `.html` files. To opt out: `{{ trusted_html
| safe }}`. In this app the news titles are pre-built as HTML `<a>` tags in `news.py`, and pandas'
`DataFrame.to_html(escape=False)` renders them unescaped (`renderer.py`). Safe *only* because the
input (NewsAPI titles) is trusted. If you ever pipe untrusted strings through `escape=False`,
you've created an XSS hole.

### 6.6 url_for — the right way to write links

```html
<a href="{{ url_for('run_detail', run_id=run.id) }}">#{{ run.id }}</a>
```
Reverse routing: pass the endpoint name (function name by default) + URL params. Flask builds the
URL from the URL map. Why it matters: change the URL pattern and all links update automatically;
params get URL-encoded for free; `url_for('static', filename='app.css')` produces `/static/app.css`
— and Flask serves any file under `static/` automatically; you didn't write a route. Hardcoded
paths in templates are a code smell. Always `url_for`.

### 6.7 The complete request → response example

A click on "Run Now" from the dashboard:
1. Browser sends `POST /runs`.
2. Flask matches `(POST, "/runs")` → `run_now`.
3. `run_now` checks for an in-progress run, spawns a daemon thread to call `run_report(...)`, calls
   `flash("Report run started…")`, returns `redirect(url_for("runs"))` → HTTP 302 with `Location: /runs`.
4. Browser sees 302, sends `GET /runs`.
5. Flask matches → `runs`, queries the DB, renders `runs.html`.
6. `runs.html` extends `base.html`. `base.html` calls `get_flashed_messages()` which pops the
   "Report run started" message. The renderer also walks the runs list, one row per run.
7. Browser receives HTML, parses, downloads `app.css`, renders. Page shows the new running row at
   top with status badge "running" + the flash banner above.

Meanwhile in another thread, `run_report` is hitting FMP, downloading data, rendering charts. When
it finishes it updates the DB row to `succeeded`. The user can refresh to see it. That's the loop.

---

## Layer 7 — The actual HTML structure

### 7.1 The document skeleton

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>...</title>
  <link rel="stylesheet" href="...">
</head>
<body>...</body>
</html>
```
- `<!doctype html>` — modern (HTML5) parsing rules. Without it, browsers fall into "quirks mode."
  **Always include it.**
- `<html lang="en">` — accessibility (screen readers) and translation tools.
- `<meta charset="utf-8">` — text encoding. Must be in the first 1024 bytes. Use UTF-8, always.
- `<meta name="viewport" ...>` — tells mobile browsers to render at device width. Without it, the
  site looks tiny on phones.
- `<link rel="stylesheet">` — fetch and apply a CSS file.
- `<title>` — browser tab text and search-result title.

### 7.2 Semantic tags

The base layout uses semantic HTML rather than wall-to-wall `<div>`s: `<header>` (top of page),
`<nav>` (navigation), `<main>` (main content), `<section>` (a thematic grouping — each card/panel),
`<dl>`/`<dt>`/`<dd>` (definition list, label/value pairs — the stat cards), `<table>`/`<thead>`/
`<tbody>`/`<tr>`/`<th>`/`<td>` (the runs/reports tables), `<form>`/`<input>`/`<button>`/`<label>`
(the settings page). Browsers don't enforce semantic tags, but screen readers, search engines, and
your future self benefit. A `<nav>` lets a screen reader user skip directly to navigation.

### 7.3 Forms in detail

Simplest one — "Run Now":
```html
<form method="post" action="{{ url_for('run_now') }}">
  <button type="submit">Run Now</button>
</form>
```
A form is the browser's mechanism for sending structured data to the server. On submit the browser:
(1) collects all form-control values into name=value pairs; (2) encodes them per the form's `enctype`
(default `application/x-www-form-urlencoded`); (3) sends an HTTP request with the form's `method`
(`get`/`post`) to the form's `action` URL. For a button-only form, no extra data — the act of
POSTing is the signal.

The settings form is more elaborate:
```html
<form class="settings-form" method="post" action="{{ url_for('update_settings_view') }}">
  {% for field in fields %}
    {% if field.type == "multicheckbox" %}
      <div class="settings-field">
        <span>{{ field.label }}</span>
        <div class="checkbox-group">
          {% for option_value, option_label in field.options %}
            <label class="checkbox-item">
              <input type="checkbox" name="{{ field.key }}" value="{{ option_value }}"
                     {% if option_value in field.value %}checked{% endif %}>
              <span>{{ option_label }}</span>
            </label>
          {% endfor %}
        </div>
      </div>
    {% else %}
      <label>
        <span>{{ field.label }}</span>
        {% if field.type == "checkbox" %}
        <input type="checkbox" name="{{ field.key }}" {% if field.value %}checked{% endif %}>
        {% else %}
        <input type="{{ field.type }}" step="any" name="{{ field.key }}" value="{{ field.value }}">
        {% endif %}
      </label>
    {% endif %}
  {% endfor %}
  <button type="submit">Save Settings</button>
</form>
```
Things to internalize: **`name`** is what gets sent; **`value`** is the current data; **labels
wrapping inputs** make the label clickable and are required for accessibility. **`type` matters**:
`number` shows a numeric keyboard + spinners; `email` does browser-side validation; `checkbox` only
sends if checked. **Multiple inputs with the same `name`** (multicheckbox) → server sees a list
(`request.form.getlist(name)`). **`checked` is a boolean attribute** — presence = true; absence =
false; the `{% if condition %}checked{% endif %}` pattern is idiomatic. **Confirmation dialogs**
like `onsubmit="return confirm('...')"` are tiny inline JavaScript — `confirm()` returns true/false;
if false, the form doesn't submit.

### 7.4 Tables

```html
<table>
  <thead><tr><th>ID</th><th>Status</th>...</tr></thead>
  <tbody>
    {% for run in runs %}
      <tr><td>...</td></tr>
    {% endfor %}
  </tbody>
</table>
```
`<thead>`/`<tbody>` separate header from data rows so `<th>` gets default bold styling, sticky
headers/accessibility tools work, and pagination can target `<tbody>`. `class="badge status-{{
run.status }}"` interpolates the status string into the class name, so one CSS rule
(`.status-succeeded { background: green }`) styles each row by data.

### 7.5 Why no JavaScript framework

The entire app is server-rendered HTML. No React/Vue, no fetch calls. Every interaction is a full
page load. Pros: drastically simpler (one language: Python + HTML); works without JS; no bundler/
transpilation/`npm install`. Cons: every action is a round-trip + reload — feels less snappy; rich
interactions (drag-drop, charts, autocomplete) are awkward. For a single-user dashboard,
server-rendered is correct. For a customer-facing app with rich UX, add React/Vue/Svelte for the
interactive parts (or HTMX for incremental enhancement). **Don't reach for a JS framework unless you
need interactivity HTML can't deliver.**

---

## Layer 8 — CSS, the visual layer

CSS = Cascading Style Sheets. Three things to learn first: **selectors** (which elements?), **the
box model** (how is each element sized?), **layout systems** (Flexbox and Grid).

### 8.1 The actual file

`web/static/app.css` is one ~290-line file. The head:
```css
:root {
  --bg: #f5f7fa;
  --surface: #ffffff;
  --line: #d8dee8;
  --text: #18212f;
  --muted: #697586;
  --accent: #16697a;
  --accent-strong: #0b4f5c;
  --danger: #a32929;
  --success: #256f3a;
  --warn: #8a5a00;
}
```
`:root` matches the `<html>` element. Variables here (CSS custom properties — start with `--`) are
inherited by everything; reference with `var(--bg)`. This is a **design tokens** pattern. Re-skin
the whole app by changing ten values.

```css
* { box-sizing: border-box; }
```
`*` selects every element. `box-sizing: border-box` changes the box model: by default an element's
`width` is the *content* width and `padding`/`border` add to it; `border-box` says "width = content
+ padding + border, all together." This is what you want 99% of the time.

```css
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: "Aptos", "Segoe UI", sans-serif;
}
```
Reset the default body margin (browsers add 8px), set background/text color/fonts. The font stack is
"try Aptos, fall back to Segoe UI, fall back to whatever the system calls 'sans-serif'." Always
include a fallback.

### 8.2 Selectors

```css
.topbar { ... }              /* class selector */
.topbar nav { ... }          /* descendants: <nav> inside .topbar */
.topbar nav a { ... }        /* deeper descendants */
.button-link:hover { ... }   /* pseudo-class: when hovered */
button:disabled { ... }      /* pseudo-class: when disabled attribute set */
input[type="checkbox"] { ... } /* attribute selector */
```
Specificity: `id > class > tag`. When two rules conflict, the more specific one wins; ties broken by
document order. Don't fight specificity with `!important` everywhere — restructure.

### 8.3 Layout: Flexbox

```css
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  padding: 0.85rem 1.5rem;
  background: #12232e;
  color: white;
}
```
`display: flex` turns the element into a flex container; direct children become flex items laid out
in a row by default. `align-items: center` — vertical alignment (cross axis). `justify-content:
space-between` — horizontal distribution (main axis): first item left, last right, gap between.
`gap` — space between items. `padding: 0.85rem 1.5rem` — top/bottom 0.85rem, left/right 1.5rem.
Mental model: "I have a row of items, distribute them along this axis, align them across the
perpendicular axis." Perfect for nav bars, button groups, label+control pairs.

`rem` is "root em" — a multiple of the root font size (default 16px). Using `rem` instead of `px`
makes the design scale if the user changes their browser font size (accessibility).

### 8.4 Layout: Grid

```css
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
  margin: 0;
}
```
Grid is for two-dimensional layouts. `grid-template-columns` defines the column structure:
`repeat(auto-fit, ...)` — make as many columns as fit; `minmax(180px, 1fr)` — each column is at
least 180px wide but expands to share leftover space (`1fr` = "one fraction of the remaining
space"). So on a wide screen you get ~5 stat cards in a row; on narrow, 2 or 1, **without media
queries**. Responsive layout done by the engine itself. The settings form uses the same trick with
`minmax(240px, 1fr)`.

### 8.5 The badge component

```css
.badge {
  display: inline-block;
  border-radius: 999px;
  padding: 0.15rem 0.5rem;
  font-size: 0.82rem;
  font-weight: 650;
  background: #edf2f7;
}
.status-succeeded { background: #e3f4e8; color: var(--success); }
.status-failed    { background: #fbe8e8; color: var(--danger); }
.status-running   { background: #fff3cf; color: var(--warn); }
```
A badge is a pattern: small, pill-shaped, color-coded. The base class sets shape; modifier classes
set color. HTML applies both: `class="badge status-succeeded"`. This is a tiny version of **BEM
(Block, Element, Modifier)** — a CSS naming convention to avoid global-style chaos. `border-radius:
999px` is a hack for "fully rounded ends" — anything bigger than half the height does it.

### 8.6 Media queries

```css
@media (max-width: 720px) {
  .topbar, .header-row, .actions {
    flex-direction: column;
    align-items: stretch;
  }
  table { display: block; overflow-x: auto; }
}
```
Apply these rules only when the viewport is ≤720px wide. The topbar stacks vertically; tables get
horizontal scroll. **Mobile-responsive design**: same HTML, restyled at narrower widths. Modern best
practice is "mobile-first" — write the small-screen CSS as the default, then `@media (min-width:
720px)` for desktop overrides. This file does it the older way (desktop default + mobile override).
Both work.

### 8.7 What's not here

No animations, transitions, or dark mode. All achievable with a few more rules — `transition:
background 0.15s ease;` on buttons, `prefers-color-scheme` media queries for dark mode. The app
keeps it minimal because it's an internal tool.

---

## Layer 9 — Background work (threads & scheduling)

You can't run the report-generation pipeline inside an HTTP request handler — it takes seconds to
minutes, and the HTTP socket would time out. Two patterns: (1) **external worker** (Celery, RQ —
a separate process pulls jobs from a queue); (2) **in-process background thread** — what this app
uses. Trade-off: option 2 is simple (no extra services) but couples worker capacity to web capacity,
dies if the web process crashes, doesn't scale to multiple replicas. For one user on a homelab,
option 2 wins.

### 9.1 Manual run via thread

```python
@app.post("/runs")
def run_now():
    ...
    db_path = app.config["DB_PATH"]
    def target() -> None:
        try:
            run_report(db_path=db_path, trigger="web")
        except Exception:
            app.logger.exception("Manual report run failed")
    threading.Thread(target=target, daemon=True).start()
    flash("Report run started. Refresh run history to see progress.")
    return redirect(url_for("runs"))
```
`Thread(target=fn, daemon=True)` spawns a daemon thread. **Daemon** = "if the main process exits,
kill this thread." Without it, `Ctrl+C` waits for the report to finish. The `try/except` is critical:
an uncaught exception in a thread won't crash the process but disappears silently unless logged. The
closure captures `db_path` from the outer scope.

### 9.2 The scheduler

`scheduler.py` defines `ReportScheduler`, a class wrapping a long-running thread that wakes every
`interval_seconds` (default 60s), checks current time/date against settings, decides whether to fire
`run_report`. Architecture:

```
┌─ Flask process ────────────────────────────┐
│  Werkzeug HTTP server (request thread)     │
│  ReportScheduler thread (60s tick loop)    │
│  Manual-run threads (daemon, on demand)    │
└────────────────────────────────────────────┘
        ↓ all share state via SQLite
   data/financial_market_report.sqlite3
```

The decision logic in `tick()`:
```python
def tick(self, now=None) -> bool:
    config = self._load_effective_config()
    tz = ZoneInfo(config.report.timezone)
    checked_at = now.astimezone(tz) if now else datetime.now(tz)
    self._set_state(last_checked_at=format_scheduler_datetime(checked_at), last_error=None)

    if not config.schedule.enabled:                          # gate 1: enabled?
        return False
    scheduled_at = self._scheduled_at(config, checked_at)
    if not self._is_scheduled_day(config, scheduled_at):     # gate 2: right day?
        return False
    if checked_at < scheduled_at:                            # gate 3: time has passed?
        return False
    run_date = scheduled_at.date().isoformat()
    if self._already_handled(run_date):                      # gate 4: already done in memory?
        return False
    if scheduled_run_exists(self.db_path, run_date=run_date, trigger="schedule"):
        self._set_state(last_run_date=run_date)              # gate 5: already done in DB?
        return False
    if get_running_report_run(self.db_path) is not None:     # gate 6: a run already in progress?
        return False
    return self._run_report(run_date=run_date, started_at=checked_at)
```
Six gates, each cheaper than the next is more expensive. "Check cheap things first, escalate" is
good defensive design. A `threading.Lock` protects the in-memory fields (`_running`,
`_last_run_date`, etc.) from races between the tick loop and callers of `status()`. SQLite handles
its own locking. `_already_handled` + `scheduled_run_exists` is belt-and-suspenders: in-memory state
is fast but lost on restart; the DB query covers restarts. The dashboard reads `scheduler.status()`
to show "Next Run / Last Check / State"; that method recomputes `next_run_at` by walking up to 8
days forward looking for an enabled day.

### 9.3 Why no APScheduler or cron

`APScheduler` adds a dependency and a different mental model. `cron` requires a separate process;
you'd lose the in-process state visibility on the dashboard. A 60-line manual loop is good enough
for one fire/day. Bigger systems use Celery Beat + Celery workers, sometimes a Kubernetes CronJob.
For a homelab dashboard, manual is fine.

---

## Layer 10 — Configuration (deep)

### 10.1 Frozen dataclasses

```python
@dataclass(frozen=True)
class ReportSettings:
    max_tickers: int = 50
    price_of_interest: float = 30.0
    ...
```
`@dataclass` generates `__init__`, `__repr__`, `__eq__` from type annotations. `frozen=True` makes
instances immutable (assignment raises). Why immutable? Easy to reason about (nobody mutates config
mid-run); hashable (usable as dict keys); forces overrides to flow through `apply_settings_overrides`,
which produces a *new* config rather than mutating the old one. Three settings classes (`Report`,
`Schedule`, `Email`) plus a wrapper `AppConfig` holding all three. Strict separation makes it
obvious what concerns belong where.

### 10.2 The override merging algorithm

```python
def apply_settings_overrides(config: AppConfig, flat_settings: Mapping[str, Any]) -> AppConfig:
    report = asdict(config.report)
    schedule = asdict(config.schedule)
    email = asdict(config.email)
    sections = {"report": report, "schedule": schedule, "email": email}
    for key, raw_value in flat_settings.items():
        section_name, separator, field_name = key.partition(".")
        if not separator:
            continue
        section = sections.get(section_name)
        if section is None or field_name not in section:
            continue
        value = _decode_override_value(raw_value)
        section[field_name] = _coerce_override_value(value, section[field_name])
    schedule = _normalize_schedule_settings(schedule)
    email = _normalize_email_settings(email)
    return AppConfig(
        report=ReportSettings(**report),
        schedule=ScheduleSettings(**schedule),
        email=EmailSettings(**email),
    )
```
Walk through: (1) convert each frozen dataclass to a mutable dict (`asdict`); (2) for each
`section.field` key in SQLite settings, route to the right dict; (3) JSON-decode the stored string,
then **coerce to the type of the existing default** (`_coerce_override_value` — how `"true"` from a
checkbox becomes `True`, `"30"` becomes `30`); (4) run section-specific normalizers (compute
`use_ssl` from `smtp_port`, sort `run_days`); (5) construct fresh frozen dataclasses + a fresh
`AppConfig`. This is a **typed-merge**; it rejects keys that don't map to a known section/field, so
a junk row in `settings` doesn't blow up the app.

### 10.3 Elegant vs could-be-better

Elegant: single source of truth (the dataclass defaults define both the type and the fallback);
frozen + reconstructed = no accidental mutation; `_coerce_override_value` handles ugly type coercion
in one place. Could be better: no schema validation (`max_tickers = -5` is silently used —
Pydantic would catch it); the flat-key convention (`report.max_tickers`) is hand-maintained — no
enforcement that a UI key matches a dataclass field. Adding a setting requires editing the dataclass
*and* `SETTING_FIELDS` in `app.py` *and* the YAML defaults. For your own apps, either lean on
Pydantic (`BaseSettings`) or use a registration pattern to keep the lists in sync.

---

## Layer 11 — Secrets resolution

```python
def read_secret(name: str, *, required: bool = True) -> str | None:
    value = _read_vault_secret(name)
    if value:
        return value
    value = _read_env_or_file(name)
    if value:
        return value
    if required:
        ...
        raise RuntimeError(f"Missing required secret '{name}'. Provide it ...")
    return None
```
Three sources, in order: (1) **Vault** (the production source) — on first call `_read_vault_secret`
does one `read_secret_version` to pull the entire secret payload, caches the resulting dict in a
module-level variable, returns the requested key; (2) **environment variable** (the dev/CI source);
(3) **file on disk** under `/run/secrets/<NAME>` or `<project>/secrets/<NAME>` (Docker-secrets
convention).

Module-level cache caveats: cache lives until process restart; a `clear_secret_cache()` function is
provided and called by the `/secrets` UI route to force re-read (useful after rotating a secret); a
Vault error caches an *empty* dict so subsequent calls don't keep retrying — you'd need
`clear_secret_cache()` to retry. The Vault bootstrap variables (`VAULT_ADDR`, `VAULT_TOKEN`, etc.)
are explicitly **excluded** from Vault lookups — otherwise you'd have a chicken-and-egg loop reading
the Vault address from Vault. Pattern: **layer your secret sources** with a clear precedence and a
single resolution function. Don't sprinkle `os.environ.get(...)` calls across your codebase.

---

## Layer 12 — Storage (SQLite + repository pattern)

### 12.1 Why SQLite

SQLite is a library, not a server. The "database" is one file. No separate process, no network, no
auth. For single-writer workloads it's superb. If you needed multiple writers, replication, or
strong concurrency: PostgreSQL. The conceptual jump is "replace `connect()` with a connection pool +
adjust minor SQL syntax variants" — the architecture above this layer wouldn't change.

### 12.2 The schema

Five tables (defined in `db.py`):

| Table | Role | Notes |
|---|---|---|
| `settings` | flat key/value runtime overrides | upserted via `INSERT ... ON CONFLICT(key) DO UPDATE` |
| `report_runs` | one row per pipeline execution | `status` constrained to `running\|succeeded\|failed`; `params_json` records the effective config |
| `reports` | one row per generated HTML file | FK to `report_runs(id)`, `ON DELETE CASCADE` |
| `ticker_candidates` | filtered tickers per run | wide row + `row_json` blob holds the raw record |
| `news_articles` | news per run | similar shape |

The "store the typed columns I care about *and* the raw JSON" pattern (`row_json`) is pragmatic:
typed columns are queryable/indexable, but the raw JSON preserves anything you didn't bother typing.
Don't go overboard — eventually you'll want everything typed.

### 12.3 Connection lifecycle

```python
def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```
Each call opens a fresh connection. SQLite connections are cheap; this trades a tiny bit of overhead
for simplicity (no pool, no thread-affinity issues). `row_factory = sqlite3.Row` makes rows
dict-like (`row["status"]` instead of `row[3]`). `PRAGMA foreign_keys = ON` is **per-connection** in
SQLite — not a global database setting. Forget it and your `ON DELETE CASCADE` silently doesn't
work. The `with connect(...) as conn:` blocks commit on success and rollback on exception — sqlite3's
`Connection` is a context manager that does this.

### 12.4 The repository pattern

`storage/repository.py` is a flat module of functions: `create_report_run`, `finish_report_run`,
`update_settings`, `list_reports`, etc. No classes, no ORM. Each function: (1) calls `init_db(db_path)`
(idempotent — `CREATE TABLE IF NOT EXISTS` is cheap); (2) opens a connection; (3) runs one or two
parameterized queries; (4) returns rows or counts. Why not an ORM (SQLAlchemy)? Raw SQL pros: smaller
dep footprint; the SQL is *the* contract — no ORM magic to debug; easy to read for anyone who knows
SQL. Cons: no automatic migrations; harder to refactor on schema change; easy to introduce SQL
injection if you forget `?` placeholders (this codebase uses placeholders correctly throughout). For
a five-table app, raw SQL wins. For 50 tables with relations evolving over years, an ORM earns its
keep.

### 12.5 The `report_runs.params_json` trick

Every row stores the *full* effective config used for that run as JSON:
```python
params = {"config": asdict(config), "runtime": {"trigger": trigger, ...}}
run_id = create_report_run(db_path, started_at=generated_at, params=params)
```
This is **immutable history** — even if you change the YAML, runs from yesterday still know what
they ran with. The scheduler uses this to dedupe scheduled runs (`scheduled_run_exists` reads
`params_json`, looks for `runtime.trigger == "schedule"`). For your own apps: when an action has a
config and you want "what was that run like?" later, snapshot the config into the row.

---

## Layer 13 — External APIs and pandas

### 13.1 The HTTP client pattern

```python
def _get_json(endpoint, *, api_key, timeout=30):
    url = f"{FMP_BASE_URL}/{endpoint}"
    try:
        response = requests.get(url, params={"apikey": api_key}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"FMP API request failed for {endpoint}: {exc.__class__.__name__}") from None
    except ValueError:
        raise RuntimeError(f"FMP API returned invalid JSON for {endpoint}") from None
    return data if isinstance(data, list) else []
```
Five things to copy into your habits: (1) **always pass `timeout=`** — the default is "wait forever";
a hung remote hangs your scheduler thread indefinitely; (2) **`raise_for_status()`** turns 4xx/5xx
into Python exceptions; (3) **pass parameters as `params=`**, not f-string concatenation —`requests`
URL-encodes them safely; (4) **catch `requests.exceptions.RequestException`** as the generic
network-error catch; (5) **`from None`** suppresses the original traceback chain — the new error is
a clean abstraction.

### 13.2 pandas as the in-memory data shape

The pipeline passes `pandas.DataFrame` objects around as the universal currency. Each external API's
response is normalized into a DataFrame; filters operate on DataFrames; the renderer calls
`df.to_html(...)`. For a project this size, clean. Downside: every reader needs pandas idioms
(`df[df["col"] > x]`, `.copy()`, `.reset_index(drop=True)`). For known, small data shapes, plain
dicts/lists would be lighter. pandas is justified here because the operations (group, filter, sort,
dedupe across multiple frames) are exactly its strength.

---

## Layer 14 — Reporting (HTML, charts, email)

### 14.1 The HTML report

`reporting/renderer.py` is *not* a Flask template — it's a standalone HTML string built by f-string.
Why? The report has to open from disk in a browser without a Flask process, and be emailed and
rendered by a mail client. A self-contained HTML file with inline `<style>` and `<img>`-by-filename
is the most portable shape. `render_report_html` takes four pieces of data (interest table, events,
news, charts) and slots them in. The image src mode parameter switches between `"relative"` (→
`<img src="AAPL_5m_1d.png">`, works on disk and via Flask's `/reports/<id>/<filename>` route) and
`"cid"` (→ `<img src="cid:AAPL_5m_1d.png">`, for email body).

### 14.2 Charts

`reporting/charts.py` uses `mplfinance` (built on matplotlib). Three calls per ticker: `5m/1d`
(intraday detail), `1h/7d` (week), `1h/1mo` (month). The non-obvious bit: `matplotlib.use("Agg")` at
the top of the file. `Agg` is a non-interactive backend that renders to PNG. The default backend
tries to open a window, which crashes in headless environments (Docker containers, schedulers).
**Always set `Agg` for server-side plotting.** Charts are saved as PNGs to
`reports/<date>/<TICKER>_<interval>_<period>.png`. Each one is closed via `plt.close(fig)` to release
memory — matplotlib leaks figures otherwise.

### 14.3 Email (MIME structure)

`emailer/smtp.py` builds a multipart message:
```
multipart/mixed                     ← outer (allows attachments)
├── multipart/related               ← groups inline content with its assets
│   ├── multipart/alternative       ← plain + HTML versions of the body
│   │   ├── text/plain
│   │   └── text/html
│   └── image/png × N               ← inline charts, each Content-ID: <filename>
└── application/html                ← the report file as an attachment
```
Why so nested? Mail clients have wildly different rendering preferences. Plain-text-only clients pick
the `text/plain` branch. HTML clients pick the `text/html` branch. Inline images are siblings of the
alternative inside `related` so the HTML can reference them via `cid:`. The `mixed` outer layer
permits the attachment to live alongside the inline body. The transport choice is port-driven: 465 →
implicit SSL (`SMTP_SSL`); anything else (typically 587) → STARTTLS upgrade. Three retry attempts
with backoff on transient failures; auth failures don't retry.

---

## Layer 15 — Building your own version, end to end

If you sat down today to build a small Flask dashboard for some other domain (say, monitoring your
homelab's uptime checks), here's the order, mirroring this project's layering:

1. **Skeleton.** `mkdir my-app && cd my-app && python -m venv .venv && source .venv/bin/activate`,
   `mkdir -p src/myapp/web/templates src/myapp/web/static tests`, write `pyproject.toml` with Flask
   as the only dep, `pip install -e .`.
2. **Hello world.** `src/myapp/web/app.py` with a `create_app()` factory + one route returning a
   string. Run with `flask --app myapp.web.app:create_app run`.
3. **Templates.** Write `base.html` with topbar/nav/main/block content. Convert your route to
   `render_template("home.html")`. Add `static/app.css` with the design-token + flexbox patterns above.
4. **Persistence.** Add `storage/db.py` with `init_db` + `connect`. Add a repository module with one
   or two functions. Pick SQLite to start.
5. **Forms.** Add a settings route with a form. Implement POST-redirect-GET. Use `flash()` for confirmation.
6. **Configuration.** Move hard-coded values into a `config.py` with frozen dataclasses + a YAML loader.
7. **Background work.** If you need scheduled work, write a `scheduler.py` modeled on this project's.
   If you need long-running on-demand work, use `threading.Thread`.
8. **Secrets.** Build a `read_secret(name)` function with the env → file → (optional) Vault chain.
9. **Containerize.** Write a small Dockerfile and compose file. Bind-mount `data/`, set a healthcheck,
   run as non-root.
10. **CLI.** Add a `cli.py` with argparse subcommands for `serve`, `init-db`, etc., wire up via
    `[project.scripts]`.
11. **Tests.** Add pytest. Use the app factory to spin up isolated apps with temp DBs.

That's a working application from zero in about a day if you've internalized the patterns above. The
whole `FinancialMarketReport` repo is essentially this recipe with a domain-specific pipeline
(FMP → filter → news → charts → HTML → email) substituted for the work step.

---

## Where to read next

- **Flask:** the official tutorial (flaskr blog) — same factory + Jinja patterns shown here.
- **Jinja:** the Template Designer Documentation.
- **CSS:** MDN's CSS Layout chapter for Flexbox and Grid; CSS-Tricks for patterns.
- **HTML:** MDN Form fundamentals.
- **SQLite + Python:** Python docs `sqlite3` module — read the "Transaction control" subsection.
- **Docker:** Nigel Poulton's *Docker Deep Dive* for depth.
