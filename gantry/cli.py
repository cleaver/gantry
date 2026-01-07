from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from gantry.port_allocator import PortAllocator
from gantry.registry import Registry

app = typer.Typer(help="Gantry: A local development environment manager.")
console = Console()

# Instantiate core components
registry = Registry()
port_allocator = PortAllocator(registry)


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
        # Basic registration, more complex logic will be added later.
        http_port = port_allocator.allocate_port()
        project = registry.register_project(hostname=hostname, path=path, port=http_port)
        
        # Add the allocated http port to the exposed ports
        registry.update_project_metadata(hostname, exposed_ports=[http_port])

        console.print(f"[green]✔ Project '{hostname}' registered successfully![/green]")
        console.print(f"  - Assigned Port: {project.port}")
        console.print(f"  - Access URL: http://{hostname}.test (after DNS setup)")

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
def update(
    hostname: str = typer.Argument(..., help="The hostname of the project to update.")
):
    """[Not Implemented] Re-scan a project and update its metadata."""
    console.print(f"'{hostname}' update command is not yet implemented.")


if __name__ == "__main__":
    app()
