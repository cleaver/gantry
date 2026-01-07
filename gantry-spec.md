# Gantry Specification
## Local Development Environment Manager

### Project Overview

**Gantry** is a Python-based CLI and TUI application that consolidates management of multiple local development projects. It provides:
- Centralized project registration and lifecycle management
- Automatic DNS resolution for `.test` domains
- Reverse proxy routing via Caddy
- SSL/TLS certificate management with system integration
- Multi-project orchestration (run multiple apps simultaneously)
- Port conflict prevention and management
- TUI management console

**Technology Stack:**
- **Language**: Python 3.12+
- **Package Manager**: `uv` (fast, lockfile-based)
- **CLI**: Typer for command parsing
- **TUI**: Textual for terminal UI
- **Reverse Proxy**: Caddy (lightweight, automatic HTTPS)
- **Certificates:** mkcert (Wrapper)  
- **DNS**: systemd-resolved or dnsmasq integration (Linux-first)
- **Data Storage**: JSON/YAML (simple, version-controllable)
- **Process Management**: psutil for monitoring, subprocess for launching

---

## Architecture Overview

```
User (CLI/TUI)
    ↓
Gantry Core (registry, lifecycle management)
    ↓
    ├─→ Process Manager (start/stop services)
    ├─→ DNS Manager (configure systemd-resolved/.test domains)
    ├─→ Caddy Manager (reverse proxy config generation)
    ├─→ Certificate Manager (mkcert integration, system CA trust)
    ├─→ Project Registry (JSON storage)
    └─→ Port Allocator (conflict detection)
    ↓
System Integration
    ├─→ systemd-resolved (DNS)
    ├─→ Caddy (reverse proxy)
    ├─→ Docker (optional services: postgres, mailhog, redis)
    ├─→ System certificate store (/usr/local/share/ca-certificates/)
    └─→ /etc/dnsmasq.d/ or systemd DNS config
```

---

## Phase 1: Core Infrastructure & Project Registration

### Objectives
- Establish project registry and storage
- Implement CLI argument parsing
- Build project registration flow
- Create basic project metadata structure

### Technical Components

#### 1.1 Project Registry System
**File**: `gantry/registry.py`

**Features:**
- Store projects in `~/.gantry/projects.json` (structured index)
- Per-project directory: `~/.gantry/projects/<hostname>/`
- Metadata includes:
  - `hostname` (e.g., `proj1`)
  - `path` (absolute path to project directory)
  - `port` (allocated HTTP port)
  - `services` (list of docker-compose services)
  - `service_ports` (map of service name → exposed port, e.g., `{"postgres": 5432, "redis": 6379}`)
  - `exposed_ports` (array of all ports used by this project, including HTTP and service ports)
  - `docker_compose` (boolean: uses docker-compose?)
  - `working_directory` (where to run commands from)
  - `environment_vars` (project-specific env vars)
  - `registered_at` (timestamp)
  - `last_started` (timestamp)
  - `status` (running, stopped, error)

**Data Structure Example:**
```json
{
  "projects": {
    "proj1": {
      "hostname": "proj1",
      "path": "/home/user/projects/myapp",
      "port": 5001,
      "services": ["app", "db"],
      "service_ports": {
        "postgres": 5432,
        "redis": 6379,
        "mailhog_smtp": 1025,
        "mailhog_web": 8025
      },
      "exposed_ports": [5001, 5432, 6379, 1025, 8025],
      "docker_compose": true,
      "working_directory": "/home/user/projects/myapp",
      "environment_vars": {},
      "registered_at": "2026-01-04T22:30:00Z",
      "last_started": null,
      "status": "stopped"
    }
  }
}
```

**Methods:**
- `register_project(hostname, path, port=None)` → validates, allocates HTTP port, detects service ports from docker-compose.yml (if present), saves all ports to metadata
- `get_project(hostname)` → returns project metadata
- `list_projects()` → returns all projects
- `unregister_project(hostname)` → removes project
- `update_project_status(hostname, status)` → sets running/stopped/error
- `get_running_projects()` → returns list of projects with status="running"
- `update_service_ports(hostname, service_ports, exposed_ports)` → updates port tracking

#### 1.2 CLI Framework
**File**: `gantry/cli.py`

**Commands:**
```
gantry register              # Interactive registration in current directory
gantry register --hostname <h> --path <p>   # Non-interactive
gantry list                  # Show all registered projects
gantry unregister <hostname> # Remove project
gantry config <hostname>     # View/edit project config
gantry status                # Show all projects + their status
gantry ports <hostname>      # Show all ports used by a project
gantry ports --all           # Show ports for all projects
```

**Implementation Notes:**
- Use `Typer` for command parsing
- Rich tables for output formatting
- Colorized output (green=running, grey=stopped, red=error, yellow=warning)
- Interactive prompts for `register` (hostname, services, docker-compose?, port allocation)
- During registration: auto-detect service ports from docker-compose.yml if present
- Show detected ports to user for confirmation/modification
- Store all ports (HTTP + services) in project metadata

#### 1.3 Port Allocator
**File**: `gantry/port_allocator.py`

**Features:**
- Allocates ports from range `5000-5999` for HTTP services (assumes standard ports for dev)
- Tracks allocated ports in registry
- Validates availability with `netstat` or `ss` command
- Prevents conflicts across projects
- Detects service ports from docker-compose.yml
- Validates port conflicts before project startup
- Provides port usage reporting

**Methods:**
- `allocate_port()` → finds first available port in 5000-5999 range, reserves it
- `is_port_available(port)` → checks if port is free (system-level check)
- `get_project_port(hostname)` → returns assigned HTTP port
- `detect_service_ports(compose_file_path)` → parses docker-compose.yml and returns map of service name → exposed port
- `check_port_conflicts(hostname, ports)` → checks if any ports conflict with running projects, returns list of conflicts
- `get_running_project_ports()` → returns dict of running project hostnames → their exposed_ports arrays
- `get_port_usage()` → returns dict mapping port → list of projects using it (for reporting)
- `validate_startup_ports(hostname)` → validates all project ports against running projects, raises PortConflictError if conflicts found

**Port Detection Details:**
- `detect_service_ports()` parses docker-compose.yml for `ports` mappings:
  - Format: `"5432:5432"` or `"5432/tcp"` → extracts host port (first number)
  - Handles both `ports:` array and single port string formats
  - Maps service name to exposed port (e.g., `{"postgres": 5432, "redis": 6379}`)
  - For services without explicit port mappings, infers from standard ports:
    - `postgres` → 5432
    - `redis` → 6379
    - `mysql` → 3306
    - `mailhog` → 1025 (SMTP), 8025 (Web UI)
- Combines HTTP port + service ports into `exposed_ports` array
- Stores both `service_ports` (mapping) and `exposed_ports` (flat list) for efficient conflict checking

**Port Conflict Detection:**
- On project startup, `validate_startup_ports()`:
  1. Gets all running projects via `registry.get_running_projects()`
  2. For each running project, retrieves its `exposed_ports` array
  3. Checks if any port in the starting project's `exposed_ports` exists in running projects
  4. Returns list of conflicts: `[{"port": 5432, "conflicting_project": "proj2", "service": "postgres"}]`
  5. If conflicts found and not forced: raises `PortConflictError` with details
  6. If conflicts found and forced: logs warning with conflict details but proceeds

**Error Handling:**
- `PortConflictError` exception includes:
  - List of conflicting ports with details
  - Which projects are using conflicting ports
  - Suggested resolution (stop conflicting project or use different ports)
- CLI displays user-friendly error message with conflict details
- `--force` flag allows bypassing conflict check (with warning)

#### 1.4 Project Auto-Detection (Nice-to-have for Phase 1)
**File**: `gantry/detectors.py`

**Auto-detect:**
- Presence of `docker-compose.yml` → assume Docker-based
- Presence of `Dockerfile` → containerized
- Service ports from `docker-compose.yml` → parse `ports` mappings to detect exposed ports
- Standard service ports (Postgres: 5432, Redis: 6379, MySQL: 3306, etc.) → infer from service names/images

### Phase 1 Checklist

#### 1.1
- [ ] Create project structure:
  ```
  gantry/
    __init__.py
    cli.py
    registry.py
    port_allocator.py
    detectors.py
    config.py
  pyproject.toml
  README.md
  ```

#### 1.2
- [ ] Implement `registry.py`:
  - [ ] JSON load/save with atomic writes
  - [ ] Project data validation
  - [ ] CRUD operations for projects
  - [ ] Status tracking

#### 1.3
- [ ] Implement `port_allocator.py`:
  - [ ] Port availability check via subprocess
  - [ ] Track allocated ports
  - [ ] Error handling for already-allocated ports
  - [ ] `detect_service_ports()` to parse docker-compose.yml for port mappings
  - [ ] `check_port_conflicts()` to validate against running projects
  - [ ] `get_running_project_ports()` to query registry for active projects
  - [ ] `validate_startup_ports()` with conflict detection
  - [ ] `get_port_usage()` for reporting which projects use which ports

#### 1.4
- [ ] Implement `cli.py` with Typer:
  - [ ] `register` command (interactive prompts)
  - [ ] `list` command (tabular output)
  - [ ] `unregister` command with confirmation
  - [ ] `status` command showing all projects
  - [ ] `config` command to view metadata

#### 1.5
- [ ] Implement `detectors.py`:
  - [ ] Docker Compose detection
  - [ ] Port detection from docker-compose.yml (parse `ports` mappings)
  - [ ] Standard service port inference (Postgres, Redis, MySQL, etc.)
  
#### 1.6
- [ ] Write tests:
  - [ ] Registry CRUD operations
  - [ ] Port allocation logic
  - [ ] Port detection from docker-compose.yml (various formats)
  - [ ] Port conflict detection (multiple projects, same ports)
  - [ ] CLI command parsing

#### 1.7
- [ ] Update dependencies in `pyproject.toml`:
  - [ ] `typer`
  - [ ] `rich` (for tables/colors)
  - [ ] `pydantic` (for validation)

#### 1.8
- [ ] Documentation:
  - [ ] Usage examples for `register`/`list`/`status`
  - [ ] Port conflict detection and resolution
  - [ ] How service ports are detected from docker-compose.yml

---

## Phase 2: Process Management & Service Lifecycle

### Objectives
- Implement process lifecycle (start/stop/restart)
- Provide access to service logs via `docker compose logs`
- Handle Docker Compose services
- Create service health checks

### Technical Components

#### 2.1 Process Manager
**File**: `gantry/process_manager.py`

**Features:**
- Start/stop/restart projects (Docker Compose)
- Monitor process status using `psutil`
- Implement health checks for services
- Port conflict detection before startup
- Warn on conflicts, optionally block startup

**Methods:**
- `start_project(hostname, force=False)` → validates ports, checks conflicts, starts services, records PID
- `stop_project(hostname)` → graceful shutdown with timeout
- `restart_project(hostname)` → stop + start
- `get_status(hostname)` → returns (running, stopped, error)
- `get_logs(hostname, service=None, follow=False)` → streams logs from `docker compose logs`
- `health_check(hostname)` → HTTP GET to localhost:port
- `check_startup_conflicts(hostname)` → checks for port conflicts, returns conflict report or None

**Implementation Details:**
- Before starting: call `port_allocator.validate_startup_ports(hostname)` to check conflicts
- If conflicts found and `force=False`: raise `PortConflictError` with details
- If conflicts found and `force=True`: log warning but proceed
- Conflict report format: `{"port": 5432, "conflicting_project": "proj2", "service": "postgres"}`
- For Docker Compose: `subprocess.Popen(['docker-compose', '-f', compose_path, 'up', '-d'])`
- For logs: `subprocess.Popen(['docker', 'compose', 'logs', '--follow', service])`
- Store PIDs in `~/.gantry/projects/<hostname>/state.json`
- Implement timeout logic (e.g., wait 30s for graceful shutdown before kill)

#### 2.2 Service Orchestration
**File**: `gantry/orchestrator.py`

**Features:**
- Start/stop multiple projects
- Handle dependencies (e.g., DB must start before app)
- Implement "auto-start" configuration per project
- Service health monitoring loop

**Methods:**
- `start_all()` → starts all "auto-start" projects
- `stop_all()` → graceful shutdown of all projects
- `get_all_status()` → dictionary of all projects → status
- `watch_services()` → background process monitoring health, auto-restart on failure (optional)

### Phase 2 Checklist

#### 2.1
- [ ] Implement `process_manager.py`:
  - [ ] `start_project()` with Docker Compose support
  - [ ] Port conflict checking before startup (call `port_allocator.validate_startup_ports()`)
  - [ ] Conflict warning/error handling with `--force` flag support
  - [ ] `check_startup_conflicts()` to generate conflict reports
  - [ ] `stop_project()` with graceful shutdown timeout
  - [ ] `restart_project()`
  - [ ] `get_status()` via PID validation
  - [ ] `get_logs()` via `docker compose logs`
  - [ ] Health check via HTTP GET + retry logic
  - [ ] Error handling (service already running, port in use, port conflicts, etc.)

#### 2.2
- [ ] Implement `orchestrator.py`:
  - [ ] `start_all()` and `stop_all()`
  - [ ] Dependency ordering for services
  - [ ] Status aggregation

#### 2.3
- [ ] Extend `registry.py`:
  - [ ] Add `auto_start` boolean field to project metadata
  - [ ] Add `last_status_change` timestamp
  - [ ] Persist PID on start
  - [ ] Add `service_ports` and `exposed_ports` fields to metadata
  - [ ] Implement `get_running_projects()` method
  - [ ] Implement `update_service_ports()` method

#### 2.4
- [ ] Extend `cli.py`:
  - [ ] `start <hostname> [--force]` command (with conflict checking)
  - [ ] `stop <hostname>` command
  - [ ] `restart <hostname>` command
  - [ ] `start-all` command
  - [ ] `stop-all` command
  - [ ] `logs <hostname> [--follow] [--service <name>]` command
  - [ ] `health-check <hostname>` command
  - [ ] `ports <hostname>` command (show all ports for a project)
  - [ ] `ports --all` command (show ports for all projects)

#### 2.5
- [ ] Update `process_manager.py`:
  - [ ] Add `port` parameter to start command (for reverse proxy)
  - [ ] Validate port is in allowed range

#### 2.6
- [ ] Tests:
  - [ ] Mock subprocess calls
  - [ ] Test start/stop lifecycle
  - [ ] Test health check logic

#### 2.7
- [ ] Documentation:
  - [ ] Examples: `gantry start proj1`, `gantry logs proj1 --follow`

---

## Phase 3: DNS Management & .test Domain Resolution

### Objectives
- Configure systemd-resolved for `.test` domain resolution
- Auto-register projects as `<hostname>.test`
- Support wildcard domains for subservices (`*.proj1.test`)
- Handle system DNS integration

### Technical Components

#### 3.1 DNS Manager
**File**: `gantry/dns_manager.py`

**Features:**
- Configure DNS resolution for `.test` TLD → `127.0.0.1`
- Use systemd-resolved (modern Linux standard)
- Fallback to dnsmasq if systemd-resolved unavailable
- Register each project as `<hostname>.test` and `*.<hostname>.test`

**Implementation:**

**Option A: systemd-resolved (Fedora, Ubuntu 18.04+)**
```python
# Create /etc/systemd/resolved.conf.d/gantry.conf
[Resolve]
DNS=127.0.0.1
Domains=~test

# Then configure Caddy to listen on 127.0.0.1:53
```

Actually, systemd-resolved **cannot** act as a DNS server by default. Better approach:

**Option B: dnsmasq (more portable)**
- Install dnsmasq if not present
- Create `/etc/dnsmasq.d/gantry.conf`:
  ```
  address=/.test/127.0.0.1
  ```
- Restart dnsmasq
- Configure `/etc/resolv.conf` to use dnsmasq (or rely on systemd-resolved → dnsmasq chaining)

**Option C: /etc/hosts file (fallback)**
- Write entries to `/etc/hosts` for each project
- Requires `sudo` but simple and portable
- Dynamic updates less elegant

**Recommended approach for Phase 3:**
Start with **Option B (dnsmasq)** since it's standard on most Linux distros. Provide fallback to `/etc/hosts`.

**Methods:**
- `setup_dns()` → checks if dnsmasq installed, installs if needed, configures
- `register_dns(hostname)` → adds entry for `hostname.test`
- `unregister_dns(hostname)` → removes entry
- `test_dns(hostname)` → verifies DNS resolution works

#### 3.2 DNS Configuration Templates
**File**: `gantry/dns_templates.py`

**Dnsmasq config template:**
```
# /etc/dnsmasq.d/gantry.conf (generated)
# Auto-generated by Gantry
# Do not edit manually; changes will be overwritten

address=/.test/127.0.0.1

# Project-specific (optional, for non-wildcard setup):
# address=/proj1.test/127.0.0.1
# address=/proj2.test/127.0.0.1
```

**Systemd-resolved integration (alternative):**
```
# /etc/systemd/resolved.conf.d/gantry.conf
[Resolve]
# Use local dnsmasq resolver for .test
DNS=127.0.0.1
Domains=~test
```

### Phase 3 Checklist

#### 3.1
- [ ] Implement `dns_manager.py`:
  - [ ] Detect available DNS backend (dnsmasq, systemd-resolved)
  - [ ] Check if dnsmasq installed, offer to install via package manager
  - [ ] `setup_dns()` with privilege escalation (sudo) handling
  - [ ] `register_dns(hostname)` to add DNS entry
  - [ ] `test_dns(hostname)` to verify resolution
  - [ ] Error handling for DNS setup failures

#### 3.2
- [ ] Implement `dns_templates.py`:
  - [ ] Template strings for dnsmasq config
  - [ ] Template for systemd-resolved config

#### 3.3
- [ ] Extend `cli.py`:
  - [ ] `dns-setup` command (one-time setup)
  - [ ] `dns-status` command (show current config)
  - [ ] `dns-test <hostname>` command

#### 3.4
- [ ] Extend `registry.py` and project registration:
  - [ ] Add `dns_registered` boolean to project metadata
  - [ ] Track DNS registration state

#### 3.5
- [ ] Integration with `register` command:
  - [ ] Auto-register DNS on project registration
  - [ ] Prompt user for sudo password if needed

#### 3.6
- [ ] Tests:
  - [ ] Mock DNS system calls
  - [ ] Test dnsmasq config generation
  - [ ] Test DNS resolution verification

#### 3.7
- [ ] Documentation:
  - [ ] Explanation of .test TLD
  - [ ] One-time setup instructions
  - [ ] Troubleshooting DNS issues

---

## Phase 4: Reverse Proxy & Certificate Management

### Objectives
- Set up Caddy as reverse proxy
- Generate and manage SSL/TLS certificates
- Auto-redirect HTTP to HTTPS
- Support subdomain routing (db.proj1.test, mail.proj1.test)
- Integrate system CA for self-signed certs

### Technical Components

#### 4.1 Caddy Manager
**File**: `gantry/caddy_manager.py`

**Features:**
- Generate Caddyfile (Caddy configuration)
- Start/stop Caddy service
- Auto-reload configuration on project changes
- Reverse proxy rules for each project
- Subdomain support for services

**Caddyfile Template:**
```caddy
# Auto-generated by Gantry
# Reverse proxy configuration for local development

{
  acme_dns internal
  email admin@localhost
}

# Project 1
proj1.test {
  reverse_proxy localhost:5001
}

db.proj1.test {
  reverse_proxy localhost:5002
}

mail.proj1.test {
  reverse_proxy localhost:1025
}

# Project 2
proj2.test {
  reverse_proxy localhost:5003
}

adminer.proj2.test {
  reverse_proxy localhost:8080
}
```

**Methods:**
- `generate_caddyfile()` → creates Caddyfile from all registered projects
- `start_caddy()` → launches Caddy with generated config
- `stop_caddy()` → gracefully stops Caddy
- `reload_caddy()` → reloads config without restarting
- `add_route(hostname, service, port)` → updates routing rules

#### 4.2 Certificate Manager
**File**: `gantry/cert_manager.py`

**Features:**
- Use `mkcert` to generate self-signed certificates
- Install CA certificate to system trust store
- Per-project or global wildcard certificate
- Manage certificate lifecycle

**Approach:**
1. Install `mkcert` if not present
2. Create local CA if not exists: `mkcert -install`
3. Generate wildcard cert for `*.test`: `mkcert '*.test'`
4. Caddy uses this cert for all .test domains
5. System automatically trusts (via mkcert -install)

**Methods:**
- `setup_ca()` → creates local CA and installs to system
- `generate_cert(domains)` → creates cert for given domains
- `get_cert_path(hostname)` → returns path to cert files
- `verify_cert_trusted()` → checks if system trusts our CA

**File structure:**
```
~/.gantry/certs/
  ca.crt              # CA certificate
  rootCA-key.pem      # CA private key
  *.test.crt          # Wildcard cert
  *.test.key          # Wildcard private key
  proj1.test.crt      # Per-project cert (optional)
  proj1.test.key
```

#### 4.3 Service Routing Configuration
**File**: `gantry/routing_config.py`

**Features:**
- Map projects to services and ports
- Define special services (Adminer for DB, MailHog for SMTP)
- Auto-detect services from docker-compose.yml
- Use `service_ports` from project registry for routing configuration

**Example mapping:**
```json
{
  "proj1": {
    "main": {
      "port": 5001,
      "domain": "proj1.test"
    },
    "db": {
      "port": 5432,
      "domain": "db.proj1.test",
      "service": "adminer"  // Special handler
    },
    "smtp": {
      "port": 1025,
      "domain": "mail.proj1.test",
      "service": "mailhog"
    }
  }
}
```

### Phase 4 Checklist

#### 4.1
- [ ] Install Caddy (download binary or via package manager):
  - [ ] Check if Caddy installed, offer installation
  - [ ] Download latest release from github.com/caddyserver/caddy
  - [ ] Place in `~/.gantry/bin/caddy`

#### 4.2
- [ ] Implement `caddy_manager.py`:
  - [ ] Generate Caddyfile from registry
  - [ ] Template for routing rules
  - [ ] `start_caddy()` with subprocess
  - [ ] `stop_caddy()` gracefully
  - [ ] `reload_caddy()` via `caddy reload` command
  - [ ] Error handling (port 80/443 already in use)

#### 4.3
- [ ] Implement `cert_manager.py`:
  - [ ] Detect/install mkcert
  - [ ] `setup_ca()` to create local CA
  - [ ] `generate_cert()` for wildcard domains
  - [ ] System CA trust verification
  - [ ] Handle cert regeneration

#### 4.4
- [ ] Implement `routing_config.py`:
  - [ ] Parse docker-compose.yml for services
  - [ ] Auto-detect Adminer for database services
  - [ ] Auto-detect MailHog for SMTP
  - [ ] Map ports from registry

#### 4.5
- [ ] Extend `cli.py`:
  - [ ] `caddy-setup` command (one-time installation)
  - [ ] `caddy-start` command
  - [ ] `caddy-stop` command
  - [ ] `caddy-reload` command
  - [ ] `routes` command (show all routing rules)
  - [ ] `cert-setup` command (generate certs)
  - [ ] `cert-status` command

#### 4.6
- [ ] Extend `registry.py`:
  - [ ] Add `services` field with port mappings
  - [ ] Add `caddy_configured` boolean
  - [ ] Add `cert_installed` boolean

#### 4.7
- [ ] Integration in `register` command:
  - [ ] Parse docker-compose.yml for services
  - [ ] Prompt for service ports
  - [ ] Auto-generate Caddyfile on registration
  - [ ] Generate certs on registration

#### 4.8
- [ ] Tests:
  - [ ] Mock Caddy subprocess
  - [ ] Test Caddyfile generation
  - [ ] Test cert generation
  - [ ] Test routing rule generation

#### 4.9
- [ ] Documentation:
  - [ ] Caddy setup instructions
  - [ ] Self-signed cert explanation
  - [ ] How to add subservices (Adminer, MailHog)
  - [ ] Troubleshooting cert trust issues

---

## Phase 5: TUI (Text User Interface)

### Objectives
- Build interactive terminal interface for advanced users
- Alternative to web console
- Real-time status, logs, and control
- Keyboard-driven navigation

### Technical Components

#### 5.1 Textual Framework Setup
**Framework**: Textual (Python TUI framework by Will McGugan)

**File**: `gantry/tui/app.py`

**Layout:**
```
┌─ Gantry Console ───────────────────────────────────────────────┐
│ Projects: [Filter]                                 Status: Ready │
├────────────────────────────────────────────────────────────────┤
│                                                                  │
│  proj1    ■ Running   (5001)   [Start] [Stop] [Logs]           │
│  proj2    ● Stopped   (5002)   [Start] [Stop] [Logs]           │
│  proj3    ▲ Error     (5003)   [Start] [Stop] [Logs]           │
│                                                                  │
├────────────────────────────────────────────────────────────────┤
│ Logs (proj1):                                                    │
│ 22:35:10 [INFO] Phoenix started on localhost:5001              │
│ 22:35:11 [INFO] LiveView connected                             │
│ 22:35:12 [INFO] Postgres connection pool ready                 │
│                                                                  │
├────────────────────────────────────────────────────────────────┤
│ Commands: 's' start | 'd' stop | 'l' logs | 'q' quit           │
└────────────────────────────────────────────────────────────────┘
```

#### 5.2 Textual Widgets
**Components:**
- Project list (interactive table)
- Status display (color-coded)
- Log viewer (scrollable, live-updating)
- Command palette (keyboard shortcuts)
- Footer (help text)

**Key bindings:**
- `↑/↓` → Navigate projects
- `Enter` or `Space` → Toggle start/stop
- `l` → View logs for selected project
- `r` → Restart selected project
- `a` → Start all projects
- `A` → Stop all projects
- `q` → Quit
- `?` → Help/keybindings

### Phase 5 Checklist

#### 5.1
- [ ] Add Textual to dependencies

#### 5.2
- [ ] Create TUI app structure:
  - [ ] `tui/app.py` (main Textual application)
  - [ ] `tui/widgets.py` (custom widgets)
  - [ ] `tui/screens.py` (different screens/views)

#### 5.3
- [ ] Implement main screen:
  - [ ] Project table with columns: Name, Status, Port, Actions
  - [ ] Color-coded status indicators
  - [ ] Selection/focus handling
  - [ ] Real-time status updates

#### 5.4
- [ ] Implement log viewer:
  - [ ] Scrollable log display
  - [ ] Service selector
  - [ ] Live-tail functionality
  - [ ] Clear logs button

#### 5.5
- [ ] Implement action handlers:
  - [ ] Start/Stop/Restart buttons
  - [ ] Keyboard shortcuts
  - [ ] Confirmation dialogs
  - [ ] Loading states

#### 5.6
- [ ] Extend `cli.py`:
  - [ ] `tui` command to launch TUI console
  - [ ] Alternative to web console

#### 5.7
- [ ] Tests:
  - [ ] Mock Textual widgets
  - [ ] Test key bindings
  - [ ] Test status updates

#### 5.8
- [ ] Documentation:
  - [ ] Screenshot of TUI
  - [ ] Keybindings reference
  - [ ] Usage: `gantry tui`

---

## Phase 6: Docker Service Integration

### Objectives
- Simplify database and third-party service setup
- Auto-start Docker containers (Postgres, Redis, MailHog, Adminer)
- Manage Docker networks
- Centralized service configuration

### Technical Components

#### 6.1 Docker Service Manager
**File**: `gantry/docker_service_manager.py`

**Features:**
- Auto-create shared Docker network (`gantry-local`)
- Pre-built Docker Compose configs for common services
- Option to use project's own docker-compose.yml or centralized services
- Health checks for Docker services

**Supported services:**
- PostgreSQL (configurable version)
- Redis
- MySQL
- MailHog (SMTP testing)
- Adminer (DB client)

**Configuration template:**
```yaml
# ~/.gantry/services/docker-compose.yml (optional)
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: gantry
      POSTGRES_PASSWORD: gantry
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - gantry-local

  redis:
    image: redis:7-alpine
    networks:
      - gantry-local

  mailhog:
    image: mailhog/mailhog:latest
    networks:
      - gantry-local
    ports:
      - "1025:1025"  # SMTP
      - "8025:8025"  # Web UI

volumes:
  postgres_data:

networks:
  gantry-local:
    driver: bridge
```

**Methods:**
- `setup_docker_network()` → creates shared network
- `start_service(service_name)` → starts service container
- `stop_service(service_name)` → stops service container
- `health_check(service_name)` → verifies service is ready
- `get_service_port(service_name)` → returns exposed port

#### 6.2 Service Configuration
**File**: `gantry/services.py`

**Per-project service definitions:**
```json
{
  "proj1": {
    "services": {
      "postgres": {
        "enabled": true,
        "image": "postgres:15",
        "version": "15",
        "database": "proj1_dev"
      },
      "redis": {
        "enabled": false
      },
      "mailhog": {
        "enabled": true,
        "port": 1025
      },
      "adminer": {
        "enabled": true,
        "database_service": "postgres"
      }
    }
  }
}
```

### Phase 6 Checklist

#### 6.1
- [ ] Implement `docker_service_manager.py`:
  - [ ] Docker network creation
  - [ ] Service lifecycle (start/stop)
  - [ ] Health checks for containers
  - [ ] Port mapping and exposure

#### 6.2
- [ ] Create service templates:
  - [ ] `services/postgres.yml` template
  - [ ] `services/redis.yml` template
  - [ ] `services/mailhog.yml` template
  - [ ] `services/adminer.yml` template

#### 6.3
- [ ] Extend project registration:
  - [ ] Prompt for services during `register`
  - [ ] Auto-detect services from docker-compose.yml
  - [ ] Store service config in project metadata

#### 6.4
- [ ] Extend `orchestrator.py`:
  - [ ] Start services as part of project startup
  - [ ] Stop services on project shutdown
  - [ ] Health check for services

#### 6.5
- [ ] Extend `cli.py`:
  - [ ] `services <hostname>` → show enabled services
  - [ ] `service-start <hostname> <service>`
  - [ ] `service-stop <hostname> <service>`

#### 6.6
- [ ] Tests:
  - [ ] Mock Docker CLI calls
  - [ ] Test service startup/shutdown
  - [ ] Test health checks

#### 6.7
- [ ] Documentation:
  - [ ] Supported services and versions
  - [ ] Configuration examples
  - [ ] Service health check details

---

## Phase 7: Advanced Features & Polish

### Objectives
- Add convenience features
- Improve user experience
- Performance optimization
- Comprehensive documentation

### Features to Implement

#### 7.1 Environment Variable Management
- Per-project `.env` files stored in `~/.gantry/projects/<hostname>/`
- CLI to set/get environment variables
- Auto-inject on service start

#### 7.2 Project Templates
- Quick-start templates for common stacks
- `gantry new <template> <hostname>` → scaffold project
- Templates: Phoenix, Rails, Next.js, FastAPI, etc.

#### 7.3 Backup & Recovery
- Snapshot project state (registry, config, certs)
- Export/import projects
- Disaster recovery

#### 7.4 Analytics & Monitoring
- Track uptime, restart frequency
- Log analysis (errors, warnings)
- Summary reports

#### 7.5 Integration Hooks
- Pre-start/post-start scripts
- Pre-stop/post-stop scripts
- Custom health checks

#### 7.6 Multi-User Support (Advanced)
- Share dev environments across team
- User-specific port ranges
- Centralized service repository

### Phase 7 Checklist

#### 7.1
- [ ] Environment variable management:
  - [ ] `gantry env set <hostname> KEY VALUE`
  - [ ] `gantry env get <hostname> KEY`
  - [ ] `gantry env list <hostname>`
  - [ ] Auto-load on project start

#### 7.2
- [ ] Project templates:
  - [ ] Template registry in `~/.gantry/templates/`
  - [ ] `gantry new <template> <hostname>`
  - [ ] Built-in templates for popular stacks

#### 7.3
- [ ] Backup & recovery:
  - [ ] `gantry backup` → export all projects
  - [ ] `gantry restore <backup_file>`
  - [ ] Compress and encrypt backups

#### 7.4
- [ ] Analytics:
  - [ ] `gantry stats <hostname>` → uptime, restarts
  - [ ] `gantry report` → summary of all projects

#### 7.5
- [ ] Hooks:
  - [ ] `pre_start`, `post_start`, `pre_stop`, `post_stop` scripts
  - [ ] Store in project config
  - [ ] Execute with project context

#### 7.6
- [ ] Documentation:
  - [ ] Full user guide
  - [ ] API reference
  - [ ] Troubleshooting section
  - [ ] Video tutorials (optional)

#### 7.7
- [ ] Testing:
  - [ ] Integration tests (full workflow)
  - [ ] End-to-end tests
  - [ ] Performance tests

#### 7.8
- [ ] Packaging & Distribution:
  - [ ] PyPI publication
  - [ ] Installation via `pip install gantry` or `uv tool install gantry`
  - [ ] Shell completion (bash, zsh)
  - [ ] Man pages

---

## Non-Functional Requirements

### Performance
- CLI commands respond in <500ms
- Project startup logs visible within 2s
- TUI updates every 500ms
- No memory leaks in long-running processes

### Reliability
- Graceful error handling (no panic/crash)
- Atomic writes to registry (no corruption)
- Service restart on failure (optional recovery mode)
- Log rotation to prevent disk filling

### Security
- No credentials stored in plaintext
- Certificate validation
- Input sanitization for all CLI arguments

### Compatibility
- Linux (primary target): Fedora, Ubuntu, Arch, Debian
- Python 3.10+
- Works with existing docker-compose.yml files
- No dependencies on macOS-specific tools (discussed as Linux-first)

### Maintainability
- Well-structured codebase (clear module separation)
- Comprehensive tests (unit, integration, e2e)
- Documentation (inline code comments, user guide, API reference)
- Version management via `uv`

---

## Development Environment Setup

**Prerequisites:**
- Python 3.10+
- `uv` (installed via `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker & Docker Compose
- Git

**Initial setup:**
```bash
# Clone repository
git clone https://github.com/yourusername/gantry.git
cd gantry

# Create virtual environment with uv
uv venv
source .venv/bin/activate

# Install dependencies (includes dev dependencies)
uv pip install -e ".[dev]"

# Run tests
pytest

# Run CLI
gantry --help

# Build distribution
uv build
```

**Project structure:**
```
gantry/
  .github/
    workflows/
      tests.yml        # CI/CD pipeline
      release.yml      # Release automation
  gantry/
    __init__.py
    __main__.py        # Entry point
    cli.py
    config.py
    registry.py
    port_allocator.py
    process_manager.py
    orchestrator.py
    dns_manager.py
    caddy_manager.py
    cert_manager.py
    routing_config.py
    detectors.py
    docker_service_manager.py
    tui/
      __init__.py
      app.py
      widgets.py
      screens.py
    tests/
      test_registry.py
      test_cli.py
      test_process_manager.py
      # ... more tests
  pyproject.toml
  uv.lock
  README.md
  CONTRIBUTING.md
  LICENSE
```

**pyproject.toml structure:**
```toml
[project]
name = "gantry"
version = "0.1.0"
description = "Local development environment manager"
requires-python = ">=3.10"
dependencies = [
    "typer>=0.9",
    "rich>=13.0",
    "pydantic>=2.0",
    "textual>=0.30",
    "psutil>=5.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "black>=23.0",
    "ruff>=0.1",
    "mypy>=1.0",
]

[project.scripts]
gantry = "gantry.cli:app"
```

---

## Timeline & Milestones

| Phase | Estimated Duration | Deliverable |
|-------|-------------------|------------|
| **1** | 1-2 weeks | CLI with project registration, registry management |
| **2** | 1-2 weeks | Process lifecycle management, logging |
| **3** | 1 week | DNS configuration, .test domain resolution |
| **4** | 2 weeks | Caddy reverse proxy, certificate management |
| **5** | 1 week | TUI console (alternative to web) |
| **6** | 1-2 weeks | Docker service integration |
| **7** | 2-3 weeks | Polish, docs, distribution, CI/CD |
| **Total** | **9-13 weeks** | Full feature set, production-ready |

---

## Testing Strategy

### Unit Tests (Per module)
- Registry CRUD operations
- Port allocation logic
- Port detection from docker-compose.yml (various port mapping formats)
- Port conflict detection (multiple projects with overlapping ports)
- DNS config generation
- Caddyfile generation
- Certificate generation

### Integration Tests
- Full project lifecycle (register → start → stop → unregister)
- Port conflict detection on startup (two projects with same service ports)
- Port conflict warning/error handling with --force flag
- DNS resolution verification
- Caddy routing verification
- Docker service startup

### End-to-End Tests
- Register project, start all services, verify web access
- Check DNS works
- Check SSL certificate trusted
- View logs from TUI and web console
- Restart services, verify recovery

### Continuous Integration
- GitHub Actions workflow
- Run tests on every push
- Code coverage reporting
- Lint & format checks (black, ruff)
- Type checking (mypy)

---

## Documentation Plan

1. **README.md**
   - Quick start guide
   - Feature overview
   - Installation instructions

2. **GETTING_STARTED.md**
   - Step-by-step walkthrough
   - Screenshots
   - Common workflows

3. **CLI_REFERENCE.md**
   - All commands with examples
   - Flags and options
   - Exit codes and errors

4. **CONFIGURATION.md**
   - Project metadata structure
   - Environment variables
   - Service configuration

5. **TROUBLESHOOTING.md**
   - Common issues and solutions
   - DNS debugging
   - Caddy logging
   - Docker debugging

6. **CONTRIBUTING.md**
   - Development setup
   - Code standards
   - Pull request process

7. **API_REFERENCE.md** (for developers)
   - Core module APIs
   - Data structures

---

## Success Criteria

✅ User can register a project with a single command
✅ Services (app, DB, SMTP) start/stop with one command
✅ Project accessible via `proj1.test` in browser with HTTPS
✅ DNS resolution works automatically
✅ Self-signed certificate trusted by system (no warnings)
✅ Multiple projects can run simultaneously
✅ Logs accessible from CLI, web, and TUI
✅ No port conflicts
✅ Graceful error handling
✅ Comprehensive documentation
✅ <100ms CLI response time
✅ All tests passing
✅ Distributed via PyPI

---

## Future Enhancements (Post-MVP)

- Kubernetes support for pseudo-prod environments
- Team collaboration features (shared environments)
- Slack/Discord notifications for service failures
- Performance monitoring and profiling
- Automatic log aggregation (ELK stack integration)
- GraphQL API alternative to REST
- Mobile app for project monitoring
- IDE integrations (VS Code extension, JetBrains plugin)
- Ansible-like playbooks for complex setup workflows
- S3 backup integration for disaster recovery
- **Log Management for Native Processes**: A system to capture, view, and rotate logs for services that don't run in Docker.

---
