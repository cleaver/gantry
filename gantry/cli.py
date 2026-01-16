import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from gantry.caddy_manager import CaddyCommandError, CaddyManager, CaddyMissingError, install_caddy
from gantry.detectors import detect_services, detect_service_ports, rescan_project
from gantry.dns_manager import (
    DNSBackendNotFoundError,
    DNSConfigError,
    DNSManager,
    DNSTestError,
    DNSMASQ_CONFIG_DIR,
)
from gantry.orchestrator import Orchestrator
from gantry.port_allocator import PortAllocator, PortConflictError
from gantry.process_manager import (
    DockerComposeNotFoundError,
    ProcessManager,
    ProcessManagerError,
    ServiceAlreadyRunningError,
    ServiceNotRunningError,
)
from gantry.registry import Registry

app = typer.Typer(help="Gantry: A local development environment manager.")
console = Console()

# Instantiate core components
registry = Registry()
port_allocator = PortAllocator(registry)
process_manager = ProcessManager(registry, port_allocator)
orchestrator = Orchestrator(registry, process_manager)
dns_manager = DNSManager()


def get_status_color(status: str) -> str:
    """Get color for a project status."""
    if status == "running":
        return "green"
    elif status == "stopped":
        return "grey70"
    elif status == "error":
        return "red"
    return "white"


@app.command()
def register(
    hostname: Optional[str] = typer.Option(
        None, "--hostname", "-h", help="The hostname for the project (e.g., 'my-app')."
    ),
    path: Path = typer.Option(
        ".", "--path", "-p", help="The path to the project directory.",
        exists=True, file_okay=False, dir_okay=True, readable=True, resolve_path=True
    ),
):
    """Register a new project with Gantry."""
    # This is the non-interactive flow. Interactive flow will be added later.
    if not hostname:
        hostname = typer.prompt("Enter a hostname for the project")
        if not hostname:
            console.print("[red]Hostname cannot be empty.[/red]")
            raise typer.Exit(1)

    try:
        console.print(f"Registering project at '{path}' with hostname '{hostname}'...")
        http_port = port_allocator.allocate_port()
        project = registry.register_project(hostname=hostname, path=path, port=http_port)
        
        registry.update_project_metadata(hostname, exposed_ports=[http_port])

        console.print(f"[green]✔ Project '{hostname}' registered successfully![/green]")
        console.print(f"  - Assigned Port: {project.port}")

        # Check and set up DNS
        try:
            dns_status = dns_manager.get_dns_status()
            if dns_status.get("dns_configured"):
                registry.update_project_metadata(hostname, dns_registered=True)
                console.print(f"  - Access URL: http://{hostname}.test")
            else:
                console.print(f"[yellow]DNS for .test domains is not configured.[/yellow]")
                if typer.confirm("Do you want to configure it now? (requires sudo)"):
                    dns_setup()
                    registry.update_project_metadata(hostname, dns_registered=True)
                    console.print(f"  - Access URL: http://{hostname}.test")
                else:
                    console.print(f"  - Access URL: http://localhost:{project.port}")
                    console.print("    (Run 'gantry dns-setup' later to enable .test domains)")

        except DNSBackendNotFoundError:
            install_cmd = dns_manager.get_install_command()
            console.print("[yellow]DNS feature not available: dnsmasq is not installed.[/yellow]")
            if install_cmd:
                console.print(f"  Install it with: [bold]{install_cmd}[/bold]")
            console.print(f"  - Access URL: http://localhost:{project.port}")
        except Exception as e:
            # Don't fail registration if DNS check fails
            console.print(f"[yellow]Warning: Could not check DNS status: {e}[/yellow]")
            console.print(f"  - Access URL: http://localhost:{project.port}")

    except (ValueError, RuntimeError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="list")
def list_projects():
    """Show all registered projects."""
    projects = registry.list_projects()
    if not projects:
        console.print("No projects registered yet.")
        return

    table = Table("Hostname", "Status", "Port", "Path")
    for project in sorted(projects, key=lambda p: p.hostname):
        status = project.status
        color = get_status_color(status)
        table.add_row(
            project.hostname,
            f"[{color}]{status.capitalize()}[/{color}]",
            str(project.port),
            str(project.path)
        )
    console.print(table)


@app.command()
def unregister(
    hostname: str = typer.Argument(..., help="The hostname of the project to unregister.")
):
    """Unregister a project."""
    project = registry.get_project(hostname)
    if not project:
        console.print(f"[red]Project '{hostname}' not found.[/red]")
        raise typer.Exit(1)

    if project.status == 'running':
        console.print(f"[yellow]Warning: Project '{hostname}' is currently running.[/yellow]")

    if not typer.confirm(f"Are you sure you want to unregister '{hostname}'?"):
        console.print("Unregistration cancelled.")
        raise typer.Exit()
    
    try:
        registry.unregister_project(hostname)
        console.print(f"[green]Project '{hostname}' has been unregistered.[/green]")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def status():
    """Show the status of all registered projects."""
    projects = registry.list_projects()
    if not projects:
        console.print("No projects registered yet.")
        return
        
    table = Table("Hostname", "Status")
    for project in sorted(projects, key=lambda p: p.hostname):
        status = project.status
        color = get_status_color(status)
        table.add_row(
            project.hostname,
            f"[{color}]{status.capitalize()}[/{color}]"
        )
    console.print(table)


@app.command()
def config(
    hostname: str = typer.Argument(..., help="The hostname of the project to view.")
):
    """View a project's configuration."""
    project = registry.get_project(hostname)
    if not project:
        console.print(f"[red]Project '{hostname}' not found.[/red]")
        raise typer.Exit(1)

    console.print(project.model_dump())


@app.command()
def start(
    hostname: str = typer.Argument(..., help="The hostname of the project to start."),
    force: bool = typer.Option(False, "--force", "-f", help="Force start even if port conflicts are detected.")
):
    """Start a project."""
    project = registry.get_project(hostname)
    if not project:
        console.print(f"[red]Project '{hostname}' not found.[/red]")
        raise typer.Exit(1)

    try:
        # Placeholder for Caddy integration. In a future phase, this would
        # call `get_caddy_path()` to ensure Caddy is available before starting
        # the reverse proxy.
        # from gantry.caddy_manager import get_caddy_path
        # get_caddy_path()

        # Check for conflicts first
        conflicts = process_manager.check_startup_conflicts(hostname)
        if conflicts and not force:
            console.print(f"[yellow]Port conflicts detected for '{hostname}':[/yellow]")
            for conflict in conflicts:
                console.print(f"  - Port {conflict['port']} is used by '{conflict['conflicting_project']}' ({conflict['service']})")
            console.print("[yellow]Use --force to start anyway (may cause issues).[/yellow]")
            raise typer.Exit(1)
        elif conflicts and force:
            console.print(f"[yellow]Warning: Port conflicts detected, but proceeding with --force:[/yellow]")
            for conflict in conflicts:
                console.print(f"  - Port {conflict['port']} is used by '{conflict['conflicting_project']}' ({conflict['service']})")

        console.print(f"Starting project '{hostname}'...")
        process_manager.start_project(hostname, force=force)
        console.print(f"[green]✔ Project '{hostname}' started successfully![/green]")
        if project.port:
            console.print(f"  - Access URL: http://localhost:{project.port}")
            console.print(f"  - Domain: http://{hostname}.test (after DNS setup)")

    except CaddyMissingError:
        console.print("[red]Caddy is not installed. Please run 'gantry setup install-caddy' to install it.[/red]")
        raise typer.Exit(1)
    except ServiceAlreadyRunningError:
        console.print(f"[yellow]Project '{hostname}' is already running.[/yellow]")
        raise typer.Exit(0)
    except PortConflictError as e:
        console.print(f"[red]Port conflicts detected:[/red]")
        for conflict in e.conflicts:
            console.print(f"  - Port {conflict['port']} is used by '{conflict['conflicting_project']}' ({conflict['service']})")
        console.print("[yellow]Use --force to start anyway (may cause issues).[/yellow]")
        raise typer.Exit(1)
    except DockerComposeNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except (ProcessManagerError, ValueError) as e:
        console.print(f"[red]Error starting project: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def stop(
    hostname: str = typer.Argument(..., help="The hostname of the project to stop.")
):
    """Stop a project."""
    project = registry.get_project(hostname)
    if not project:
        console.print(f"[red]Project '{hostname}' not found.[/red]")
        raise typer.Exit(1)

    try:
        # Check if already stopped
        status = process_manager.get_status(hostname)
        if status == "stopped":
            console.print(f"[yellow]Project '{hostname}' is already stopped.[/yellow]")
            raise typer.Exit(0)

        console.print(f"Stopping project '{hostname}'...")
        process_manager.stop_project(hostname)
        console.print(f"[green]✔ Project '{hostname}' stopped successfully![/green]")

    except ServiceNotRunningError:
        console.print(f"[yellow]Project '{hostname}' is not running.[/yellow]")
        raise typer.Exit(0)
    except (ProcessManagerError, ValueError) as e:
        console.print(f"[red]Error stopping project: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def restart(
    hostname: str = typer.Argument(..., help="The hostname of the project to restart.")
):
    """Restart a project."""
    project = registry.get_project(hostname)
    if not project:
        console.print(f"[red]Project '{hostname}' not found.[/red]")
        raise typer.Exit(1)

    try:
        console.print(f"Restarting project '{hostname}'...")
        console.print("  Stopping...")
        process_manager.stop_project(hostname)
        console.print("  Starting...")
        process_manager.start_project(hostname)
        console.print(f"[green]✔ Project '{hostname}' restarted successfully![/green]")
        if project.port:
            console.print(f"  - Access URL: http://localhost:{project.port}")

    except (ProcessManagerError, ValueError) as e:
        console.print(f"[red]Error restarting project: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="stop-all")
def stop_all():
    """Stop all running projects."""
    running_projects = registry.get_running_projects()
    if not running_projects:
        console.print("[yellow]No running projects to stop.[/yellow]")
        raise typer.Exit(0)

    console.print(f"Stopping {len(running_projects)} project(s)...")
    stopped = orchestrator.stop_all()
    
    if stopped:
        console.print(f"[green]✔ Successfully stopped {len(stopped)} project(s):[/green]")
        for hostname in stopped:
            console.print(f"  - {hostname}")
    else:
        console.print("[yellow]No projects were stopped.[/yellow]")


@app.command()
def logs(
    hostname: str = typer.Argument(..., help="The hostname of the project."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output."),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Filter logs by service name.")
):
    """View logs for a project."""
    project = registry.get_project(hostname)
    if not project:
        console.print(f"[red]Project '{hostname}' not found.[/red]")
        raise typer.Exit(1)

    try:
        process = process_manager.get_logs(hostname, service=service, follow=follow)
        
        if follow:
            console.print(f"[green]Following logs for '{hostname}'" + (f" (service: {service})" if service else "") + "...[/green]")
            console.print("[dim]Press Ctrl+C to stop following logs.[/dim]\n")
            try:
                for line in process.stdout:
                    console.print(line.rstrip())
            except KeyboardInterrupt:
                process.terminate()
                console.print("\n[yellow]Stopped following logs.[/yellow]")
        else:
            # Read all available logs
            stdout, _ = process.communicate()
            if stdout:
                console.print(stdout)
            else:
                console.print(f"[yellow]No logs available for '{hostname}'.[/yellow]")

    except (ValueError, ProcessManagerError) as e:
        console.print(f"[red]Error getting logs: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="health-check")
def health_check(
    hostname: str = typer.Argument(..., help="The hostname of the project to check.")
):
    """Perform a health check on a project."""
    project = registry.get_project(hostname)
    if not project:
        console.print(f"[red]Project '{hostname}' not found.[/red]")
        raise typer.Exit(1)

    if not project.port:
        console.print(f"[yellow]Project '{hostname}' has no port configured for health checks.[/yellow]")
        raise typer.Exit(0)

    try:
        console.print(f"Checking health of '{hostname}' at http://localhost:{project.port}...")
        is_healthy = process_manager.health_check(hostname)
        
        if is_healthy:
            console.print(f"[green]✔ Project '{hostname}' is healthy![/green]")
            raise typer.Exit(0)
        else:
            console.print(f"[red]✗ Project '{hostname}' health check failed.[/red]")
            raise typer.Exit(1)

    except (ValueError, ProcessManagerError) as e:
        console.print(f"[red]Error performing health check: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def ports(
    hostname: Optional[str] = typer.Argument(None, help="The hostname of the project. Omit for all projects."),
    all_projects: bool = typer.Option(False, "--all", help="Show ports for all projects.")
):
    """Show ports used by a project or all projects."""
    if all_projects or hostname is None:
        # Show ports for all projects
        usage = port_allocator.get_port_usage()
        if not usage:
            console.print("No ports in use.")
            return

        table = Table("Port", "Projects", "Services")
        for port in sorted(usage.keys()):
            projects = usage[port]
            # Get service names for each project
            service_info = []
            for proj_name in projects:
                proj = registry.get_project(proj_name)
                if proj:
                    # Find which service uses this port
                    services = [s for s, p in proj.service_ports.items() if p == port]
                    if services:
                        service_info.append(f"{proj_name}:{services[0]}")
                    elif proj.port == port:
                        service_info.append(f"{proj_name}:http")
                    else:
                        service_info.append(proj_name)
            
            table.add_row(
                str(port),
                ", ".join(projects),
                ", ".join(service_info) if service_info else "-"
            )
        console.print(table)
    else:
        # Show ports for single project
        project = registry.get_project(hostname)
        if not project:
            console.print(f"[red]Project '{hostname}' not found.[/red]")
            raise typer.Exit(1)

        if not project.exposed_ports:
            console.print(f"[yellow]Project '{hostname}' has no ports configured.[/yellow]")
            return

        table = Table("Port", "Service", "Type")
        for port in sorted(project.exposed_ports):
            if port == project.port:
                service = "http"
                port_type = "HTTP"
            else:
                # Find service name for this port
                service = next((s for s, p in project.service_ports.items() if p == port), "unknown")
                port_type = "Service"
            
            table.add_row(str(port), service, port_type)
        
        console.print(f"Ports for project '{hostname}':")
        console.print(table)


@app.command()
def update(
    hostname: str = typer.Argument(..., help="The hostname of the project to update."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without applying."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-apply all changes without confirmation.")
):
    """Re-scan a project and update its metadata."""
    project = registry.get_project(hostname)
    if not project:
        console.print(f"[red]Project '{hostname}' not found.[/red]")
        raise typer.Exit(1)

    # Check if project path still exists
    if not project.path.is_dir():
        console.print(f"[red]Project directory '{project.path}' does not exist.[/red]")
        raise typer.Exit(1)

    # Re-scan project
    console.print(f"Re-scanning project '{hostname}'...")
    changes = rescan_project(project.path, project)

    # Check if project is running
    is_running = process_manager.get_status(hostname) == "running"
    if is_running:
        console.print(f"[yellow]Warning: Project '{hostname}' is currently running. Changes may require a restart.[/yellow]")

    # Generate diff/changelog
    has_changes = bool(changes)
    if not has_changes:
        console.print(f"[green]No changes detected for project '{hostname}'.[/green]")
        raise typer.Exit(0)

    # Display changes
    console.print("\n[bold]Detected Changes:[/bold]")
    
    if changes.get("services_added"):
        console.print(f"[green]Services added:[/green] {', '.join(changes['services_added'])}")
    if changes.get("services_removed"):
        console.print(f"[red]Services removed:[/red] {', '.join(changes['services_removed'])}")
    if changes.get("ports_added"):
        port_list = [f"{s}:{p}" for s, p in changes['ports_added'].items()]
        console.print(f"[green]Ports added:[/green] {', '.join(port_list)}")
    if changes.get("ports_removed"):
        console.print(f"[red]Ports removed:[/red] {', '.join(changes['ports_removed'])}")
    if changes.get("ports_changed"):
        port_list = [f"{s}:{changes['ports_changed'][s]}" for s in changes['ports_changed']]
        console.print(f"[yellow]Ports changed:[/yellow] {', '.join(port_list)}")
    if changes.get("docker_compose_removed"):
        console.print("[red]Docker Compose file removed.[/red]")

    # Check for port conflicts with running projects
    # Find docker-compose file
    compose_file = None
    if (project.path / "docker-compose.yml").exists():
        compose_file = project.path / "docker-compose.yml"
    elif (project.path / "docker-compose.yaml").exists():
        compose_file = project.path / "docker-compose.yaml"
    
    if compose_file:
        new_service_ports = detect_service_ports(compose_file)
        # Calculate new exposed ports (HTTP port + all service ports)
        new_exposed_ports = [project.port] if project.port else []
        new_exposed_ports.extend(new_service_ports.values())
        
        conflicts = port_allocator.check_port_conflicts(hostname, new_exposed_ports)
        if conflicts:
            console.print("\n[yellow]Port conflicts detected with running projects:[/yellow]")
            for conflict in conflicts:
                console.print(f"  - Port {conflict['port']} is used by '{conflict['conflicting_project']}' ({conflict['service']})")
            if not yes and not dry_run:
                console.print("[yellow]You may need to stop conflicting projects before applying updates.[/yellow]")

    # Dry run mode
    if dry_run:
        console.print("\n[yellow]Dry run mode: No changes applied.[/yellow]")
        raise typer.Exit(0)

    # Confirm before applying (unless --yes)
    if not yes:
        if not typer.confirm("\nApply these changes?"):
            console.print("Update cancelled.")
            raise typer.Exit(0)

    # Apply updates
    try:
        console.print("\nApplying updates...")
        
        # Get updated service and port information
        # Find docker-compose file
        compose_file = None
        if (project.path / "docker-compose.yml").exists():
            compose_file = project.path / "docker-compose.yml"
        elif (project.path / "docker-compose.yaml").exists():
            compose_file = project.path / "docker-compose.yaml"
        
        if compose_file:
            updated_services = detect_services(compose_file)
            updated_service_ports = detect_service_ports(compose_file)
            docker_compose = True
        else:
            updated_services = []
            updated_service_ports = {}
            docker_compose = False

        # Recalculate exposed ports
        updated_exposed_ports = []
        if project.port:
            updated_exposed_ports.append(project.port)
        updated_exposed_ports.extend(updated_service_ports.values())

        # Update metadata
        registry.update_project_metadata(
            hostname,
            services=updated_services,
            service_ports=updated_service_ports,
            exposed_ports=updated_exposed_ports,
docker_compose=docker_compose
        )

        # Update Caddy routing if configured (Phase 4)
        try:
            from gantry.caddy_manager import CaddyManager
            
            # Check if Caddy is configured by trying to generate/reload
            caddy_manager = CaddyManager(registry)
            # Regenerate Caddyfile with updated project information
            caddy_manager.generate_caddyfile()
            # Reload Caddy configuration if it's running
            try:
                caddy_manager.reload_caddy()
                console.print("[green]✔ Caddy routing updated and reloaded.[/green]")
            except Exception as e:
                # Caddy might not be running, that's okay
                console.print(f"[dim]Note: Caddy reload skipped ({e}).[/dim]")
        except ImportError:
            # Caddy manager not implemented yet (Phase 4), skip silently
            pass
        except Exception as e:
            # If Caddy is configured but update fails, warn but don't fail the update
            console.print(f"[yellow]Warning: Could not update Caddy routing: {e}[/yellow]")

        console.print(f"[green]✔ Project '{hostname}' updated successfully![/green]")
        if is_running:
            console.print("[yellow]Note: Project is running. You may want to restart it to apply changes.[/yellow]")

    except ValueError as e:
        console.print(f"[red]Error updating project: {e}[/red]")
        raise typer.Exit(1)


# --- Setup Commands ---
setup_app = typer.Typer(help="Perform one-time setup for Gantry dependencies.")
app.add_typer(setup_app, name="setup")


@setup_app.command("install-caddy")
def install_caddy_command():
    """Download and install the Caddy binary."""
    console.print("Installing Caddy...")
    try:
        install_caddy()
    except Exception as e:
        console.print(f"[red]Error installing Caddy: {e}[/red]")
        raise typer.Exit(1)


# --- Caddy Commands ---
caddy_app = typer.Typer(help="Manage the Caddy reverse proxy.")
app.add_typer(caddy_app, name="caddy")

def _get_caddy_manager():
    try:
        return CaddyManager(registry)
    except CaddyMissingError:
        console.print("[red]Caddy is not installed. Please run 'gantry setup install-caddy' to install it.[/red]")
        raise typer.Exit(1)

@caddy_app.command("start")
def caddy_start():
    """Start the Caddy server."""
    caddy_manager = _get_caddy_manager()
    try:
        console.print("Starting Caddy server...")
        caddy_manager.start_caddy()
        console.print("[green]✔ Caddy server started successfully.[/green]")
    except CaddyCommandError as e:
        console.print(f"[red]Error starting Caddy: {e}[/red]")
        console.print("[yellow]It might already be running, or there might be a port conflict (80, 443).[/yellow]")
        raise typer.Exit(1)

@caddy_app.command("stop")
def caddy_stop():
    """Stop the Caddy server."""
    caddy_manager = _get_caddy_manager()
    try:
        console.print("Stopping Caddy server...")
        caddy_manager.stop_caddy()
        console.print("[green]✔ Caddy server stopped successfully.[/green]")
    except CaddyCommandError as e:
        console.print(f"[red]Error stopping Caddy: {e}[/red]")
        console.print("[yellow]It might already be stopped.[/yellow]")
        raise typer.Exit(1)

@caddy_app.command("reload")
def caddy_reload():
    """Generate a new Caddyfile and reload the Caddy server."""
    caddy_manager = _get_caddy_manager()
    try:
        console.print("Generating Caddyfile and reloading Caddy...")
        caddy_manager.reload_caddy()
        console.print("[green]✔ Caddy configuration reloaded successfully.[/green]")
    except CaddyCommandError as e:
        console.print(f"[red]Error reloading Caddy: {e}[/red]")
        console.print("[yellow]Is the Caddy server running?[/yellow]")
        raise typer.Exit(1)

@caddy_app.command("generate-config")
def caddy_generate_config():
    """Generate the Caddyfile and print it to the console."""
    caddy_manager = _get_caddy_manager()
    console.print("[bold]Generated Caddyfile:[/bold]")
    caddyfile = caddy_manager.generate_caddyfile()
    console.print(caddyfile)


# --- DNS Commands ---
dns_app = typer.Typer(help="Manage DNS configuration for .test domains.")
app.add_typer(dns_app, name="dns")


@dns_app.command("setup")
def dns_setup():
    """One-time setup for DNS resolution."""
    console.print("Configuring DNS for .test domains...")

    # Check if dnsmasq is installed
    if not dns_manager.check_dnsmasq_installed():
        install_cmd = dns_manager.get_install_command()
        console.print("[red]dnsmasq is not installed.[/red]")
        if install_cmd:
            console.print(f"Please install it using: [bold]{install_cmd}[/bold]")
        else:
            console.print("Please install dnsmasq using your system's package manager.")
        raise typer.Exit(1)

    # Check if we need sudo
    if not os.access(DNSMASQ_CONFIG_DIR, os.W_OK):
        console.print("[yellow]Sudo privileges are required to write DNS configuration.[/yellow]")
        if not typer.confirm("Do you want to proceed?", default=True):
            console.print("DNS setup cancelled.")
            raise typer.Exit(0)

    try:
        dns_manager.setup_dns()
        console.print("[green]✔ DNS configured successfully![/green]")
        console.print("  - All *.test domains will now resolve to 127.0.0.1.")
        console.print("You may need to restart your browser for changes to take effect.")
    except (DNSBackendNotFoundError, DNSConfigError) as e:
        console.print(f"[red]Error setting up DNS: {e}[/red]")
        raise typer.Exit(1)


@dns_app.command("status")
def dns_status():
    """Show the current DNS configuration status."""
    try:
        status = dns_manager.get_dns_status()
        
        table = Table("DNS Feature", "Status")
        
        backend_status = f"[green]{status['backend']}[/green]" if status['backend'] else "[red]Not Found[/red]"
        table.add_row("DNS Backend (dnsmasq)", backend_status)
        
        config_status = "[green]Configured[/green]" if status['dns_configured'] else "[red]Not Configured[/red]"
        table.add_row("Gantry DNS Config", config_status)
        
        if status['config_exists']:
            table.add_row("Config File Path", str(status['config_file']))
        
        console.print(table)

    except DNSBackendNotFoundError:
        console.print("[yellow]dnsmasq is not installed. DNS features are disabled.[/yellow]")
    except Exception as e:
        console.print(f"[red]An unexpected error occurred: {e}[/red]")
        

@dns_app.command("test")
def dns_test(
    hostname: str = typer.Argument("example", help="The hostname to test (e.g., 'my-app').")
):
    """Test DNS resolution for a given hostname."""
    test_domain = f"{hostname}.test"
    console.print(f"Testing DNS resolution for [bold]{test_domain}[/bold]...")

    try:
        if dns_manager.test_dns(hostname):
            console.print(f"[green]✔ Success![/green] '{test_domain}' resolves to 127.0.0.1.")
        else:
            # This case should be caught by the exception but is here for safety
            console.print(f"[red]✗ Failure.[/red] Unexpected result for '{test_domain}'.")
            raise typer.Exit(1)
            
    except DNSTestError as e:
        console.print(f"[red]✗ DNS resolution failed: {e}[/red]")
        console.print("\n[bold]Troubleshooting steps:[/bold]")
        console.print("1. Ensure you have run [bold]gantry dns-setup[/bold].")
        console.print("2. Check your system's DNS settings to ensure '127.0.0.1' is listed as a resolver.")
        console.print("3. Restart your browser or system.")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
