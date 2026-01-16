"""
Manages the Caddy binary, including installation and path resolution.

This module follows the "Managed Binary" pattern. It attempts to find the Caddy
binary on the system, and if it's missing, it provides functions to download
a pinned version to a local directory (~/.gantry/bin/).
"""
import platform
import shutil
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

CADDY_VERSION = "2.7.6"
CADDY_BIN_DIR = Path.home() / ".gantry" / "bin"
CADDY_PATH = CADDY_BIN_DIR / "caddy"
CADDY_URL_PATTERN = "https://github.com/caddyserver/caddy/releases/download/v{version}/caddy_{version}_linux_{arch}.tar.gz"


class CaddyMissingError(Exception):
    """Raised when the Caddy binary cannot be found."""
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
    if CADDY_PATH.exists() and CADDY_PATH.is_file() and CADDY_PATH.stat().st_mode & 0o111:
        return CADDY_PATH

    # Fallback to checking the system PATH
    if (path := shutil.which("caddy")):
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
