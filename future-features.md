# Future Features

### Web Console

#### Objectives
- Build web dashboard for project management
- Implement start/stop/restart via web
- Show real-time logs
- Display health status
- Provide simple, focused interface

#### Technical Components

##### xxx.1 Web Framework Setup
**Framework**: FastAPI + HTML/CSS (lightweight, no heavy frontend build)

**File Structure:**
```
gantry/
  web/
    __init__.py
    app.py              # FastAPI app
    routes.py           # API endpoints
    templates/
      index.html
      project.html
      logs.html
    static/
      style.css
      script.js
```

##### xxx.2 FastAPI Application
**File**: `gantry/web/app.py`

**Endpoints:**
- `GET /` → dashboard (list all projects)
- `GET /api/projects` → JSON list of projects + status
- `GET /api/projects/<hostname>` → project details
- `POST /api/projects/<hostname>/start` → start project
- `POST /api/projects/<hostname>/stop` → stop project
- `POST /api/projects/<hostname>/restart` → restart
- `GET /api/projects/<hostname>/logs` → tail logs (with streaming)
- `GET /api/projects/<hostname>/health` → health check status
- `GET /api/status` → all projects status summary
- `WebSocket /api/logs/<hostname>` → real-time log streaming

**Implementation Notes:**
- Run FastAPI server on fixed port (e.g., 9999)
- Use CORS if needed
- Implement WebSocket for live logs
- Use `psutil` for process monitoring
- Implement auth (optional: simple token in `~/.gantry/token`)

##### xxx.3 Frontend Dashboard
**File**: `gantry/web/templates/index.html`

**Features:**
- Card layout for each project
- Color-coded status (green=running, red=stopped, yellow=error)
- Quick-action buttons (Start, Stop, Restart, View Logs)
- Real-time status updates (polling every 5s or WebSocket)
- Filter/search projects
- Show URLs for each project (proj1.test, db.proj1.test, etc.)

**Basic HTML structure:**
```html
<div class="projects">
  <div class="project-card" id="proj1">
    <h3>proj1</h3>
    <p class="status running">Running</p>
    <p class="urls">
      <a href="http://proj1.test">proj1.test</a>
      <a href="http://db.proj1.test">db.proj1.test</a>
      <a href="http://mail.proj1.test">mail.proj1.test</a>
    </p>
    <div class="actions">
      <button onclick="startProject('proj1')">Start</button>
      <button onclick="stopProject('proj1')">Stop</button>
      <button onclick="restartProject('proj1')">Restart</button>
      <button onclick="viewLogs('proj1')">Logs</button>
    </div>
  </div>
  <!-- More project cards... -->
</div>
```

##### xxx.4 Logs Viewer
**File**: `gantry/web/templates/logs.html`

**Features:**
- Real-time tail of logs (WebSocket)
- Scrollable terminal-like view
- Service selector dropdown
- Download log file option
- Auto-scroll toggle

### xxx Checklist

#### xxx.1
- [ ] Setup FastAPI project:
  - [ ] Add FastAPI, uvicorn to dependencies
  - [ ] Create `web/app.py` with FastAPI instance
  - [ ] Create `web/routes.py` with API endpoints

#### xxx.2
- [ ] Implement API endpoints in `routes.py`:
  - [ ] `GET /` (serve dashboard HTML)
  - [ ] `GET /api/projects` (list projects + status)
  - [ ] `GET /api/projects/<hostname>` (project details)
  - [ ] `POST /api/projects/<hostname>/start`
  - [ ] `POST /api/projects/<hostname>/stop`
  - [ ] `POST /api/projects/<hostname>/restart`
  - [ ] `GET /api/projects/<hostname>/logs` (tail logs)
  - [ ] `GET /api/status` (quick overview)
  - [ ] `WebSocket /ws/logs/<hostname>` (streaming logs)

#### xxx.3
- [ ] Create frontend templates:
  - [ ] `templates/index.html` (dashboard)
  - [ ] Responsive card layout
  - [ ] Service URL display
  - [ ] Action buttons

#### xxx.4
- [ ] Create static assets:
  - [ ] `static/style.css` (styling, responsive design)
  - [ ] `static/script.js` (AJAX calls, status polling, WebSocket)
  - [ ] Minimal JavaScript (no heavy frameworks yet)

#### xxx.5
- [ ] Implement WebSocket for log streaming:
  - [ ] Real-time tail of log files
  - [ ] Connection handling and reconnection

#### xxx.6
- [ ] Extend `cli.py`:
  - [ ] `web-console` or `console` command to start server
  - [ ] Print URL and access instructions
  - [ ] Graceful shutdown on Ctrl+C

#### xxx.7
- [ ] Security:
  - [ ] Optional token-based auth in headers
  - [ ] CORS configuration
  - [ ] Input validation (hostname, service names)

#### xxx.8
- [ ] Tests:
  - [ ] Mock API endpoints
  - [ ] Test JSON serialization
  - [ ] Test log streaming

#### xxx.9
- [ ] Documentation:
  - [ ] Screenshot of dashboard
  - [ ] Usage: `gantry console`
  - [ ] Default port and URL