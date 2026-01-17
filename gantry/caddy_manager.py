import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from gantry.registry import Registry
from gantry.routing_config import generate_routes_for_project

CADDY_VERSION = "2.7.6"
GANTRY_DIR = Path.home() / ".gantry"
CADDY_BIN_DIR = GANTRY_DIR / "bin"
CADDY_CONFIG_DIR = GANTRY_DIR / "caddy"
CADDY_PATH = CADDY_BIN_DIR / "caddy"
CADDY_CONFIG_PATH = CADDY_CONFIG_DIR / "Caddyfile"
CADDY_URL_PATTERN = "https://github.com/caddyserver/caddy/releases/download/v{version}/caddy_{version}_linux_{arch}.tar.gz"


class CaddyMissingError(Exception):
    """Raised when the Caddy binary cannot be found."""

    pass


class CaddyCommandError(Exception):
    """Raised when a Caddy command fails."""

    pass


def _get_architecture() -> str:
    """
    Detects the system architecture and maps it to Caddy's naming convention.

    Returns:
        The architecture string (e.g., "amd64", "arm64").

    Raises:
        SystemExit: If the architecture is unsupported.
    """
    machine = platform.machine()
    if machine == "x86_64":
        return "amd64"
    elif machine == "aarch64":
        return "arm64"
    else:
        raise SystemExit(f"Unsupported architecture: {machine}")


def check_caddy_installed() -> Path | None:
    """
    Checks if Caddy is installed locally or in the system PATH.

    1. Checks for the managed binary at `~/.gantry/bin/caddy`.
    2. Falls back to checking the system PATH using `shutil.which`.

    Returns:
        The path to the Caddy binary if found, otherwise None.
    """
    # Check for the managed binary first
    if (
        CADDY_PATH.exists()
        and CADDY_PATH.is_file()
        and CADDY_PATH.stat().st_mode & 0o111
    ):
        return CADDY_PATH

    # Fallback to checking the system PATH
    if path := shutil.which("caddy"):
        return Path(path)

    return None


def install_caddy() -> Path:
    """
    Downloads and installs a pinned version of the Caddy binary.

    - Ensures the destination directory `~/.gantry/bin/` exists.
    - Downloads the Caddy tarball for the correct architecture.
    - Displays a download progress bar using `rich.progress`.
    - Extracts the binary, sets executable permissions, and returns the path.

    Returns:
        The path to the installed Caddy binary.
    """
    arch = _get_architecture()
    download_url = CADDY_URL_PATTERN.format(version=CADDY_VERSION, arch=arch)
    tarball_path = CADDY_BIN_DIR / f"caddy_{CADDY_VERSION}.tar.gz"

    # Ensure the binary directory exists
    CADDY_BIN_DIR.mkdir(parents=True, exist_ok=True)

    # Download the tarball with a progress bar
    with Progress(
        TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "•",
        DownloadColumn(),
        "•",
        TransferSpeedColumn(),
        "•",
        TimeRemainingColumn(),
    ) as progress:
        task_id = progress.add_task("download", filename=tarball_path.name, start=False)
        with urllib.request.urlopen(download_url) as response:
            progress.update(task_id, total=int(response.info()["Content-Length"]))
            with open(tarball_path, "wb") as dest_file:
                progress.start_task(task_id)
                for data in iter(lambda: response.read(1024), b""):
                    dest_file.write(data)
                    progress.update(task_id, advance=len(data))

    # Extract the binary from the tarball
    with tarfile.open(tarball_path, "r:gz") as tar:
        # The binary is simply named 'caddy' inside the archive
        tar.extract("caddy", path=CADDY_BIN_DIR)

    # Clean up the tarball
    tarball_path.unlink()

    # Set executable permissions
    CADDY_PATH.chmod(0o755)

    print(f"Caddy v{CADDY_VERSION} installed successfully to {CADDY_PATH}")
    return CADDY_PATH


def get_caddy_path() -> Path:
    """
    Gets the path to the Caddy binary, raising an error if it's not found.

    This is the main public function to be used by other parts of the application.
    It does not automatically install Caddy, requiring explicit user consent
    via a CLI command.

    Returns:
        The path to the Caddy binary.

    Raises:
        CaddyMissingError: If the Caddy binary is not found.
    """
    path = check_caddy_installed()
    if path is None:
        raise CaddyMissingError("Caddy binary not found.")
    return path


class CaddyManager:
    def __init__(self, registry: Registry):
        self._registry = registry
        self._caddy_path = get_caddy_path()
        CADDY_CONFIG_DIR.mkdir(exist_ok=True)

    def _run_command(self, args: list[str]):
        command = [str(self._caddy_path), *args]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                cwd=CADDY_CONFIG_DIR,
            )
            return result
        except FileNotFoundError:
            raise CaddyMissingError("Caddy binary not found during command execution.")
        except subprocess.CalledProcessError as e:
            error_message = e.stderr or e.stdout
            raise CaddyCommandError(f"Caddy command failed: {error_message.strip()}")

    def generate_caddyfile(self) -> str:
        """
        Generates a Caddyfile from all registered projects.
        """
        lines = [
            "# Auto-generated by Gantry",
            "{",
            "  http_port 80",
            "  https_port 443",
            "}",
        ]

        projects = self._registry.list_projects()
        for project in projects:
            lines.append(f"\n# Project: {project.hostname}")
            routes = generate_routes_for_project(project)
            for route in routes:
                lines.append(f"{route['domain']} {{")
                lines.append(f"  reverse_proxy localhost:{route['port']}")
                lines.append("}")

        caddyfile_content = "\n".join(lines)
        CADDY_CONFIG_PATH.write_text(caddyfile_content)
        return caddyfile_content

    def start_caddy(self):
        """
        Starts the Caddy server as a background daemon.
        """
        self._run_command(["start", "--config", str(CADDY_CONFIG_PATH)])

    def stop_caddy(self):
        """
        Stops the Caddy server.
        """
        self._run_command(["stop"])

    def reload_caddy(self):
        """
        Reloads the Caddy configuration gracefully.
        """
        self.generate_caddyfile()
        self._run_command(["reload", "--config", str(CADDY_CONFIG_PATH)])
