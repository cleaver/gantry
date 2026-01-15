# Gantry

**Gantry** is a Python-based CLI application that consolidates management of multiple local development projects. It provides centralized project registration, automatic DNS resolution, reverse proxy routing, SSL/TLS certificate management, and port conflict prevention.

## Features

- **Project Registration**: Register and manage multiple local development projects
- **Port Management**: Automatic port allocation and conflict detection
- **Docker Compose Integration**: Auto-detect services and ports from `docker-compose.yml`
- **Project Lifecycle**: Start, stop, and monitor project status
- **Port Conflict Detection**: Prevent and resolve port conflicts across projects

## Installation

Install from the GitHub repository:

```bash
# Using uv (recommended)
uv pip install git+https://github.com/cleaver/gantry.git

# Or using pip
pip install git+https://github.com/cleaver/gantry.git

# For development (editable install)
git clone https://github.com/cleaver/gantry.git
cd gantry
uv pip install -e .
```

## Quick Start

### Register a Project

Register a project in the current directory:

```bash
gantry register --hostname myapp --path /path/to/project
```

Or use interactive mode:

```bash
gantry register
# Follow prompts to enter hostname and path
```

### List All Projects

```bash
gantry list
```

### Check Project Status

```bash
gantry status
```

### View Project Configuration

```bash
gantry config myapp
```

### Unregister a Project

```bash
gantry unregister myapp
```

### Process Management

#### Start a Project

Start all services for a project (e.g., Docker Compose):

```bash
gantry start myapp
```

Gantry will first check for port conflicts with other running projects. If no conflicts are found, it will start the project's services.

#### Stop a Project

Stop all services for a project:

```bash
gantry stop myapp
```

#### View Service Logs

View logs from all services in a project:

```bash
gantry logs myapp
```

To follow logs in real-time:

```bash
gantry logs myapp --follow
```

To view logs for a specific service:

```bash
gantry logs myapp --service postgres
```

## Usage Examples

### Register Command

Register a new project with Gantry:

```bash
# Non-interactive registration
gantry register --hostname myapp --path /home/user/projects/myapp

# Interactive registration (prompts for hostname)
gantry register --path /home/user/projects/myapp
```

During registration, Gantry will:
- Allocate an available HTTP port (5000-5999 range)
- Auto-detect services from `docker-compose.yml` if present
- Detect service ports from port mappings
- Create project metadata in the registry

### List Command

Display all registered projects in a table:

```bash
gantry list
```

Output shows:
- **Hostname**: Project identifier
- **Status**: Running, Stopped, or Error (color-coded)
- **Port**: Assigned HTTP port
- **Path**: Project directory path

### Status Command

Show the status of all registered projects:

```bash
gantry status
```

Status indicators:
- 🟢 **Green**: Running
- ⚪ **Grey**: Stopped
- 🔴 **Red**: Error

### Config Command

View detailed project configuration:

```bash
gantry config myapp
```

Displays all project metadata including:
- Hostname, path, port
- Services and service ports
- Exposed ports
- Docker Compose status
- Timestamps (registered_at, last_updated, last_started)
- Environment variables

### Update Command

> **Note**: The `update` command is currently under development. This section describes the planned functionality.

Re-scan a project directory and update its metadata:

```bash
# Interactive update (shows diff, prompts for confirmation)
gantry update myapp

# Preview changes without applying
gantry update myapp --dry-run

# Auto-apply all detected changes
gantry update myapp --yes
```

#### What the Update Command Does

1. **Re-scans Project Directory**: 
   - Re-reads `docker-compose.yml` (if present)
   - Detects current services and ports
   - Checks for removed `docker-compose.yml`

2. **Generates Change Diff**:
   - Services added/removed
   - Ports added/removed/changed
   - Docker Compose status changes

3. **Checks for Conflicts**:
   - Validates port conflicts with running projects
   - Warns if project is currently running (changes require restart)

4. **Applies Updates** (if confirmed):
   - Updates `services` list
   - Updates `service_ports` mapping
   - Recalculates `exposed_ports` array
   - Updates `docker_compose` boolean
   - Sets `last_updated` timestamp

#### When to Use Update

Use `gantry update` when:
- You've added or removed services in `docker-compose.yml`
- You've changed port mappings in `docker-compose.yml`
- You've removed `docker-compose.yml` from a project
- You want to refresh project metadata after manual changes

#### Handling Conflicts During Update

If port conflicts are detected:

1. **Review the conflict report**: Shows which ports conflict and which projects are using them
2. **Options**:
   - Stop the conflicting project: `gantry stop <conflicting-project>`
   - Change ports in your `docker-compose.yml` to use different ports
   - Use `--yes` flag to proceed anyway (not recommended)

Example conflict output:
```
Port conflict detected:
  Port 5432 is used by:
    - project2 (postgres service)
  
To resolve:
  1. Stop project2: gantry stop project2
  2. Or change your docker-compose.yml to use a different port
```

## Port Conflict Detection and Resolution

### How Port Conflicts Work

Gantry tracks all ports used by registered projects:
- **HTTP Port**: Main application port (5000-5999 range)
- **Service Ports**: Ports exposed by Docker Compose services (e.g., PostgreSQL, Redis)

When starting a project, Gantry checks if any of its ports conflict with currently running projects.

### Automatic Conflict Detection

Port conflicts are automatically detected:
- **During Registration**: If a port is already allocated
- **During Startup**: Before starting a project (via `gantry start`)
- **During Update**: When updating project metadata

### Resolving Port Conflicts

#### Option 1: Stop Conflicting Project

```bash
# Check which project is using the port
gantry ports --all

# Stop the conflicting project
gantry stop conflicting-project

# Start your project
gantry start myapp
```

#### Option 2: Change Ports in docker-compose.yml

Edit your `docker-compose.yml` to use different ports:

```yaml
services:
  postgres:
    ports:
      - "5433:5432"  # Changed from 5432:5432
```

Then update the project:
```bash
gantry update myapp
```

#### Option 3: Use Different HTTP Port

If the HTTP port conflicts, you can specify a different port during registration:

```bash
# Unregister and re-register with different port
gantry unregister myapp
gantry register --hostname myapp --path /path/to/project
# Port will be auto-allocated from available ports
```

### Viewing Port Usage

Check which projects are using which ports:

```bash
# Ports for a specific project
gantry ports myapp

# Ports for all projects
gantry ports --all
```

## Service Port Detection from docker-compose.yml

Gantry automatically detects service ports from your `docker-compose.yml` file during registration and updates.

### Supported Port Syntax

Gantry supports both **short** and **long** port syntax:

#### Short Syntax

```yaml
services:
  postgres:
    ports:
      - "5432:5432"      # Host:Container
      - "8080:80"        # Different host and container ports
  redis:
    ports:
      - "6379:6379"
```

Gantry extracts the **host port** (first number) for each service:
- `postgres` → port `5432`
- `redis` → port `6379`

#### Long Syntax

```yaml
services:
  postgres:
    ports:
      - target: 5432
        published: 5432
        protocol: tcp
        mode: host
  mailhog:
    ports:
      - target: 8025
        published: 8025
        protocol: tcp
```

Gantry extracts the `published` port (host port):
- `postgres` → port `5432`
- `mailhog` → port `8025`

#### Mixed Syntax

You can mix both syntaxes in the same file:

```yaml
services:
  mailhog_smtp:
    ports:
      - "1025:1025"      # Short syntax
  mailhog_web:
    ports:
      - target: 8025     # Long syntax
        published: 8025
        protocol: tcp
```

### Port Detection Behavior

- **First Port Wins**: If a service has multiple port mappings, Gantry uses the first one
- **Host Port Only**: Only ports explicitly published to the host are detected
- **Internal Ports Ignored**: Ports not exposed to the host are ignored

### Example: Complete docker-compose.yml

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "5001:5000"      # Detected: 5001
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:15
    ports:
      - "5432:5432"      # Detected: 5432
    environment:
      POSTGRES_DB: myapp

  redis:
    image: redis:7
    ports:
      - "6379:6379"      # Detected: 6379

  mailhog:
    image: mailhog/mailhog
    ports:
      - target: 1025      # Detected: 1025 (published)
        published: 1025
        protocol: tcp
      - target: 8025
        published: 8025  # Detected: 8025
        protocol: tcp
```

After registration, Gantry will track:
- HTTP port: `5001` (allocated automatically)
- Service ports: `{"app": 5001, "postgres": 5432, "redis": 6379, "mailhog": 1025}`
- Exposed ports: `[5001, 5432, 6379, 1025, 8025]`

## Project Structure

Gantry stores project data in `~/.gantry/`:

```
~/.gantry/
├── projects.json          # Main registry file
└── projects/
    ├── myapp/            # Per-project directory
    │   └── (future: logs, state, etc.)
    └── otherapp/
        └── ...
```

## Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/yourusername/gantry.git
cd gantry

# Create virtual environment with uv
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Run CLI
gantry --help
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=gantry --cov-report=html

# Run specific test file
pytest tests/test_registry.py
```

## Troubleshooting

### Port Already in Use

If you see "Port already in use" errors:

1. Check which process is using the port:
   ```bash
   lsof -i :5432
   # or
   ss -tlnp | grep 5432
   ```

2. Stop the conflicting process or change your port configuration

### Project Not Found

If you get "Project not found" errors:

1. Verify the project is registered:
   ```bash
   gantry list
   ```

2. Check the hostname spelling (case-sensitive)

### Registry Corruption

If the registry file becomes corrupted:

1. Backup current registry:
   ```bash
   cp ~/.gantry/projects.json ~/.gantry/projects.json.backup
   ```

2. Manually edit `~/.gantry/projects.json` or re-register projects

## Roadmap

See [gantry-spec.md](gantry-spec.md) for the complete development roadmap.

**Phase 1** (Current): Core Infrastructure & Project Registration ✅
- [x] Project registry and storage
- [x] CLI argument parsing
- [x] Project registration flow
- [x] Port allocation and conflict detection
- [x] Docker Compose integration

**Phase 2** (Next): Process Management & Service Lifecycle
- [ ] Start/stop/restart projects
- [ ] Service logs access
- [ ] Health checks

**Phase 3**: DNS Management & .test Domain Resolution
**Phase 4**: Reverse Proxy & Certificate Management
**Phase 5**: TUI (Text User Interface)
**Phase 6**: Advanced Features & Polish

## License

[Add your license here]

## Contributing

[Add contributing guidelines here]
