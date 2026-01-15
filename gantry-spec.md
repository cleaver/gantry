# Gantry Specification
## Local Development Environment Manager

### Project Overview

**Gantry** is a Python-based CLI and TUI application that consolidates management of multiple local development projects. It provides:
- Centralized project registration and lifecycle management
- Automatic DNS resolution for `.test` domains
- Reverse proxy routing via Caddy
- SSL/TLS certificate management with system integration
- Port conflict prevention and management
- TUI management console

**Technology Stack:**
- **Language**: Python 3.10+
- **Package Manager**: `uv` (fast, lockfile-based)
- **CLI**: Typer for command parsing
- **TUI**: Textual for terminal UI
- **Reverse Proxy**: Caddy (lightweight, automatic HTTPS)
- **Certificates:** mkcert (Wrapper)  
- **DNS**: systemd-resolved and dnsmasq integration (Linux-first)
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
    ├─→ DNS Manager (configure DNS for .test domains)
    ├─→ Caddy Manager (reverse proxy config generation)
    ├─→ Certificate Manager (mkcert integration, system CA trust)
    ├─→ Project Registry (JSON storage)
    └─→ Port Allocator (conflict detection)
    ↓
System Integration
    ├─→ systemd-resolved (DNS)
    ├─→ Caddy (reverse proxy)
    ├─→ System certificate store (/usr/local/share/ca-certificates/)
    └─→ /etc/dnsmasq.d/ DNS config
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
  - `last_updated` (timestamp, updated when project metadata is refreshed)
  - `status` (running, stopped, error)

**Implementation**:
- Can use a "temporary file and atomic rename" strategy for writing to registry to ensure the registry file is never left in a partially written state

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
      "last_updated": "2026-01-04T22:30:00Z",
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
- `update_project_metadata(hostname, **updates)` → atomic update of project metadata fields, sets last_updated timestamp

#### 1.2 CLI Framework
**File**: `gantry/cli.py`

**Commands:**
```
gantry register              # Interactive registration in current directory
gantry register --hostname <h> --path <p>   # Non-interactive
gantry list                  # Show all registered projects
gantry unregister <hostname> # Remove project
gantry update <hostname>    # Re-scan project, update metadata (interactive)
gantry update <hostname> --yes    # Auto-apply all detected changes
gantry update <hostname> --dry-run    # Show what would change without applying
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
- `update` command: re-scans project directory, detects changes, shows diff, updates metadata
  - Re-runs detection logic (services, ports, docker-compose status)
  - Compares with existing metadata to generate changelog
  - Checks for port conflicts with running projects
  - Warns if project is currently running (changes need restart)
  - Supports `--dry-run` to preview changes, `--yes` to auto-apply

**Update Command Workflow:**
1. Load existing project metadata from registry
2. Re-scan project directory using `detectors.rescan_project()`
3. Compare detected state with existing metadata
4. Generate diff showing:
   - Services added/removed
   - Ports added/removed/changed
   - docker-compose.yml status changes
5. Check for port conflicts with running projects (via `port_allocator.check_port_conflicts()`)
6. If project is running, warn that changes require restart
7. Display changes and conflicts (unless `--yes` flag)
8. Prompt for confirmation (unless `--yes` or `--dry-run`)
9. If `--dry-run`: show changes and exit without applying
10. If confirmed: apply updates via `registry.update_project_metadata()`
11. Update `last_updated` timestamp
12. If Caddy configured (Phase 4): regenerate Caddyfile and reload
13. If DNS configured (Phase 3): update DNS entries if hostname changed (shouldn't happen)

**What Gets Updated:**
- `services` (list of docker-compose service names)
- `service_ports` (map of service → port)
- `exposed_ports` (recalculated array)
- `docker_compose` (boolean, if docker-compose.yml removed)
- `last_updated` (timestamp)

**What Does NOT Change:**
- `hostname` (immutable, requires unregister/re-register)
- `port` (HTTP port, preserved unless explicitly changed)
- `registered_at` (preserved)
- `path` (preserved, but validated to still exist)

#### 1.3 Port Allocator
**File**: `gantry/port_allocator.py`

**Features:**
- Allocates ports from range `5000-5999` for HTTP services (assumes standard ports for dev)
- Tracks allocated ports in registry
- Validates availability with `netstat` or `ss` command
- Warns about potential port conflicts across projects
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
- `detect_service_ports()` parses `docker-compose.yml` for `ports` mappings to find ports exposed to the host.
  - It only considers ports explicitly published to the host (e.g., `"5432:5432"`). It extracts the host port (the first number).
  - Ports not explicitly published are considered internal to the Docker network and are ignored.
  - Handles both long and short `ports` syntax.
  - Maps service name to the exposed host port (e.g., `{"postgres": 5432}`).
- Combines the project's main HTTP port and any detected service ports into an `exposed_ports` array for conflict checking.
- Stores both `service_ports` (the service-to-port mapping) and `exposed_ports` (a flat list of all ports) in the project's metadata.

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

#### 1.4 Project Auto-Detection (Nice-to-have for Phase 1)
**File**: `gantry/detectors.py`

**Auto-detect:**
- Presence of `docker-compose.yml` → assume Docker-based project.
- Presence of `Dockerfile` → containerized project.
- Exposed service ports from `docker-compose.yml` → parse `ports` mappings to detect ports published to the host.

**Methods:**
- `detect_project_type(path)` → returns project type (docker-compose, dockerfile, native, etc.)
- `detect_services(compose_file_path)` → returns list of service names from docker-compose.yml
- `rescan_project(path, existing_metadata=None)` → re-scans project directory, returns detected changes as diff
  - Compares current state with existing_metadata (if provided)
  - Returns dict with keys: `services_added`, `services_removed`, `ports_changed`, `ports_added`, `ports_removed`
  - Handles cases where docker-compose.yml is removed or path is invalid

### Phase 1 Checklist

#### 1.1
- [x] Create project structure:
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
- [x] Implement `registry.py`:
  - [x] JSON load/save with atomic writes
  - [x] Project data validation
  - [x] CRUD operations for projects
  - [x] Status tracking
  - [x] `update_project_metadata()` method with atomic updates
  - [x] `last_updated` timestamp tracking

#### 1.3
- [x] Implement `port_allocator.py`:
  - [x] Port availability check via subprocess
  - [x] Track allocated ports
  - [x] Error handling for already-allocated ports
  - [x] `detect_service_ports()` to parse docker-compose.yml for port mappings
  - [x] `check_port_conflicts()` to validate against running projects
  - [x] `get_running_project_ports()` to query registry for active projects
  - [x] `validate_startup_ports()` with conflict detection
  - [x] `get_port_usage()` for reporting which projects use which ports

#### 1.4
- [x] Implement `cli.py` with Typer:
  - [x] `register` command (interactive prompts)
  - [x] `list` command (tabular output)
  - [x] `unregister` command with confirmation
  - [x] `update` command (re-scan project, show diff, update metadata)
  - [x] `status` command showing all projects
  - [x] `config` command to view metadata

#### 1.5
- [x] Implement `detectors.py`:
  - [x] Docker Compose detection
  - [x] Port detection from docker-compose.yml (parse `ports` mappings)
  - [x] `rescan_project()` method to detect changes and generate diff
  - [x] Handle edge cases (removed docker-compose.yml, invalid paths)
  
#### 1.6
- [x] Write tests:
  - [x] Registry CRUD operations
  - [x] Port allocation logic
  - [x] Port detection from docker-compose.yml (various formats)
  - [x] Port conflict detection (multiple projects, same ports)
  - [x] CLI command parsing
  - [x] `update` command: detect changes, generate diff, apply updates
  - [x] `update` command: handle removed docker-compose.yml
  - [x] `update` command: port conflict detection during update

#### 1.7
- [x] Update dependencies in `pyproject.toml`:
  - [x] `typer`
  - [x] `rich` (for tables/colors)
  - [x] `pydantic` (for validation)

#### 1.8
- [x] Documentation:
  - [x] Usage examples for `register`/`list`/`status`/`update`
  - [x] Port conflict detection and resolution
  - [x] How service ports are detected from docker-compose.yml
  - [x] `update` command usage: when to use, what it detects, how to handle conflicts

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
- Stop all running projects with a single command.
- Service health monitoring loop.

**Methods:**
- `stop_all()` → graceful shutdown of all running projects.
- `get_all_status()` → dictionary of all projects → status.
- `watch_services()` → background process monitoring health, auto-restart on failure (optional).

### Phase 2 Checklist

#### 2.1
- [x] Implement `process_manager.py`:
  - [x] `start_project()` with Docker Compose support
  - [x] Port conflict checking before startup (call `port_allocator.validate_startup_ports()`)
  - [x] `check_startup_conflicts()` to generate conflict reports
  - [x] `stop_project()` with graceful shutdown timeout
  - [x] `restart_project()`
  - [x] `get_status()` via PID validation
  - [x] `get_logs()` via `docker compose logs`
  - [x] Health check via HTTP GET + retry logic
  - [x] Error handling (service already running, port in use, port conflicts, etc.)

#### 2.2
- [x] Implement `orchestrator.py`:
  - [x] `stop_all()`
  - [x] Status aggregation

#### 2.3
- [x] Extend `registry.py`:
  - [x] Add `last_status_change` timestamp
  - [x] Persist PID on start (Note: PIDs are persisted by `process_manager.py` in `state.json`, not directly in `registry.py`)
  - [x] Add `service_ports` and `exposed_ports` fields to metadata
  - [x] Add `last_updated` timestamp field
  - [x] Implement `get_running_projects()` method
  - [x] Implement `update_service_ports()` method
  - [x] Implement `update_project_metadata()` method for atomic updates

#### 2.4
- [x] Extend `cli.py`:
  - [x] `start <hostname>` command (with conflict checking)
  - [x] `stop <hostname>` command
  - [x] `restart <hostname>` command
  - [x] `stop-all` command
  - [x] `logs <hostname> [--follow] [--service <name>]` command
  - [x] `health-check <hostname>` command
  - [x] `ports <hostname>` command (show all ports for a project)
  - [x] `ports --all` command (show ports for all projects)
  - [x] `update <hostname>` command implementation:
    - [x] Call `detectors.rescan_project()` to detect changes
    - [x] Generate and display diff/changelog
    - [x] Check for port conflicts with running projects
    - [x] Warn if project is currently running
    - [x] Support `--dry-run`, `--yes` flags
    - [x] Apply updates via `registry.update_project_metadata()`
    - [x] Update Caddy routing if configured (Phase 4)

#### 2.5
- [x] Update `process_manager.py`:
  - [x] Add `port` parameter to start command (for reverse proxy)
  - [x] Validate port is in allowed range

#### 2.6
- [x] Tests:
  - [x] Mock subprocess calls
  - [x] Test start/stop lifecycle
  - [x] Test health check logic

#### 2.7
- [x] Documentation:
  - [x] Examples: `gantry start proj1`, `gantry logs proj1 --follow`

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
- Use dnsmasq
- Register each project as `<hostname>.test` and `*.<hostname>.test`

**Implementation:**
- Install dnsmasq if not present
- Create `/etc/dnsmasq.d/gantry.conf`:
  ```
  address=/.test/127.0.0.1
  ```
- Restart dnsmasq
- Configure `/etc/resolv.conf` to use dnsmasq (or rely on systemd-resolved → dnsmasq chaining)

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
- [x] Implement `dns_manager.py`:
  - [x] Detect available DNS backend (dnsmasq)
  - [x] Check if dnsmasq installed, offer to install via package manager
  - [x] `setup_dns()` with privilege escalation (sudo) handling
  - [x] `register_dns(hostname)` to add DNS entry
  - [x] `test_dns(hostname)` to verify resolution
  - [x] Error handling for DNS setup failures

#### 3.2
- [x] Implement `dns_templates.py`:
  - [x] Template strings for dnsmasq config

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
- [ ] Integration in `update` command:
  - [ ] If service ports changed, regenerate Caddyfile
  - [ ] Reload Caddy configuration after update (if Caddy running)
  - [ ] Warn if project is running (routing changes need restart)

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
│  proj1    ■ Running   (5001)   [Start] [Stop] [Update] [Logs]  │
│  proj2    ● Stopped   (5002)   [Start] [Stop] [Update] [Logs]  │
│  proj3    ▲ Error     (5003)   [Start] [Stop] [Update] [Logs]  │
│                                                                  │
├────────────────────────────────────────────────────────────────┤
│ Logs (proj1):                                                    │
│ 22:35:10 [INFO] Phoenix started on localhost:5001              │
│ 22:35:11 [INFO] LiveView connected                             │
│ 22:35:12 [INFO] Postgres connection pool ready                 │
│                                                                  │
├────────────────────────────────────────────────────────────────┤
│ Commands: 's' start | 'd' stop | 'u' update | 'l' logs | 'q' quit │
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
- `u` → Update selected project (re-scan, show diff, apply changes)
- `l` → View logs for selected project
- `r` → Restart selected project
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
  - [ ] Update button and `u` key binding
  - [ ] Update dialog showing detected changes (diff view)
  - [ ] Confirmation for applying updates
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

## Phase 6: Advanced Features & Polish

### Objectives
- Add convenience features
- Improve user experience
- Performance optimization
- Comprehensive documentation

### Features to Implement

#### 6.1 Environment Variable Management
- Per-project `.env` files stored in `~/.gantry/projects/<hostname>/`
- CLI to set/get environment variables
- Auto-inject on service start

#### 6.2 Project Templates
- Quick-start templates for common stacks
- `gantry new <template> <hostname>` → scaffold project
- Templates: Phoenix, Rails, Next.js, FastAPI, etc.

#### 6.3 Backup & Recovery
- Snapshot project state (registry, config, certs)
- Export/import projects
- Disaster recovery

#### 6.4 Analytics & Monitoring
- Track uptime, restart frequency
- Log analysis (errors, warnings)
- Summary reports

#### 6.5 Integration Hooks
- Pre-start/post-start scripts
- Pre-stop/post-stop scripts
- Custom health checks

#### 6.6 Multi-User Support (Advanced)
- Share dev environments across team
- User-specific port ranges
- Centralized service repository

### Phase 6 Checklist

#### 6.1
- [ ] Environment variable management:
  - [ ] `gantry env set <hostname> KEY VALUE`
  - [ ] `gantry env get <hostname> KEY`
  - [ ] `gantry env list <hostname>`
  - [ ] Auto-load on project start

#### 6.2
- [ ] Project templates:
  - [ ] Template registry in `~/.gantry/templates/`
  - [ ] `gantry new <template> <hostname>`
  - [ ] Built-in templates for popular stacks

#### 6.3
- [ ] Backup & recovery:
  - [ ] `gantry backup` → export all projects
  - [ ] `gantry restore <backup_file>`
  - [ ] Compress and encrypt backups

#### 6.4
- [ ] Analytics:
  - [ ] `gantry stats <hostname>` → uptime, restarts
  - [ ] `gantry report` → summary of all projects

#### 6.5
- [ ] Hooks:
  - [ ] `pre_start`, `post_start`, `pre_stop`, `post_stop` scripts
  - [ ] Store in project config
  - [ ] Execute with project context

#### 6.6
- [ ] Documentation:
  - [ ] Full user guide
  - [ ] API reference
  - [ ] Troubleshooting section
  - [ ] Video tutorials (optional)

#### 6.7
- [ ] Testing:
  - [ ] Integration tests (full workflow)
  - [ ] End-to-end tests
  - [ ] Performance tests

#### 6.8
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
| **6** | 2-3 weeks | Polish, docs, distribution, CI/CD |
| **Total** | **8-11 weeks** | Full feature set, production-ready |

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
- Project update workflow (register → modify docker-compose.yml → update → verify changes)
- Port conflict detection on startup (two projects with same service ports)
- Port conflict detection during update (new ports conflict with running projects)
- DNS resolution verification
- Caddy routing verification (including after update)
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
   - `update` command: usage, flags (--dry-run, --yes), examples

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
