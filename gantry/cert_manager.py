"""
Manages the mkcert binary and local certificate authority.

This module handles the download, installation, and execution of mkcert to
create and manage a local Certificate Authority (CA) and generate
TLS certificates for development domains.
"""

import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

GANTRY_HOME = Path.home() / ".gantry"
MKCERT_VERSION = "v1.4.4"
MKCERT_BIN_DIR = GANTRY_HOME / "bin"
MKCERT_PATH = MKCERT_BIN_DIR / "mkcert"
CERTS_DIR = GANTRY_HOME / "certs"

DOWNLOAD_URL_PATTERN = "https://github.com/FiloSottile/mkcert/releases/download/{version}/mkcert-{version}-linux-{arch}"

console = Console()


class CertManager:
    """Manages the mkcert binary and certificate generation."""

    def __init__(self) -> None:
        self._mkcert_path = self._resolve_mkcert_path()
        # FIXME: The package manager should be detected from the system.
        self._package_manager = "apt"

    def _get_arch(self) -> str:
        """Determines the system architecture for mkcert URLs."""
        machine = platform.machine()
        if machine == "x86_64":
            return "amd64"
        elif machine == "aarch64":
            return "arm64"
        elif machine.startswith("arm"):
            return "arm"
        else:
            console.print(f"[bold red]Unsupported architecture: {machine}[/bold red]")
            sys.exit(1)

    def _get_system_package_name(self) -> str:
        """Detects the Linux distro and returns the appropriate package for certutil."""
        try:
            release_info = platform.freedesktop_os_release()
            os_id = release_info.get("ID")
            id_like = release_info.get("ID_LIKE", "").split()

            if os_id in ["arch", "manjaro"] or "arch" in id_like:
                return "nss"
            elif os_id in ["fedora", "rhel", "centos"] or "fedora" in id_like:
                return "nss-tools"
            elif os_id in ["debian", "ubuntu"] or "debian" in id_like:
                return "libnss3-tools"
            elif os_id == "suse" or "suse" in id_like:
                return "mozilla-nss-tools"
        except FileNotFoundError:
            # /etc/os-release not found
            pass

        # Default for unknown or other distributions
        return "libnss3-tools"

    def _resolve_mkcert_path(self) -> Path:
        """Finds mkcert, preferring the managed binary."""
        if MKCERT_PATH.exists():
            return MKCERT_PATH
        system_mkcert = shutil.which("mkcert")
        if system_mkcert:
            return Path(system_mkcert)
        return MKCERT_PATH  # Default to managed path even if it doesn't exist yet

    def check_dependencies(self) -> dict[str, bool]:
        """
        Checks for the presence of mkcert and its dependency certutil.

        Returns:
            A dictionary indicating the status of each dependency.
        """
        has_mkcert = self._mkcert_path.exists() or bool(shutil.which("mkcert"))
        has_certutil = bool(shutil.which("certutil"))
        return {"mkcert": has_mkcert, "certutil": has_certutil}

    def install_mkcert(self) -> Path:
        """
        Ensures mkcert is installed, downloading it if necessary.

        If `certutil` is not found, a warning with installation instructions
        is displayed.

        Returns:
            The path to the mkcert executable.
        """
        if self._mkcert_path.exists() and self._mkcert_path == MKCERT_PATH:
            console.print(
                f"✅ mkcert is already installed at [cyan]{self._mkcert_path}[/cyan]"
            )
            return self._mkcert_path

        if shutil.which("mkcert"):
            console.print(
                f"✅ mkcert is already installed on the system at [cyan]{shutil.which('mkcert')}[/cyan]"
            )
            return Path(shutil.which("mkcert"))

        console.print(
            f"mkcert not found. Downloading version [bold]{MKCERT_VERSION}[/bold]..."
        )

        arch = self._get_arch()
        version = MKCERT_VERSION
        url = DOWNLOAD_URL_PATTERN.format(version=version, arch=arch)

        MKCERT_BIN_DIR.mkdir(parents=True, exist_ok=True)

        try:
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
                transient=True,
            ) as progress:
                task_id = progress.add_task(
                    "download", filename=MKCERT_PATH.name, start=False
                )
                with urllib.request.urlopen(url) as response:
                    progress.update(
                        task_id, total=int(response.info().get("Content-Length", 0))
                    )
                    with open(MKCERT_PATH, "wb") as dest_file:
                        progress.start_task(task_id)
                        for data in iter(lambda: response.read(1024), b""):
                            dest_file.write(data)
                            progress.update(task_id, advance=len(data))
        except Exception as e:
            console.print(f"[bold red]Error downloading mkcert: {e}[/bold red]")
            if MKCERT_PATH.exists():
                MKCERT_PATH.unlink()
            sys.exit(1)

        # Set executable permissions
        MKCERT_PATH.chmod(MKCERT_PATH.stat().st_mode | stat.S_IEXEC)
        console.print(f"✅ Successfully installed mkcert to [cyan]{MKCERT_PATH}[/cyan]")

        # Check for certutil and warn if missing
        if not shutil.which("certutil"):
            package_name = self._get_system_package_name()
            console.print(
                f"\n[bold yellow]Warning:[/bold yellow] We downloaded mkcert, but `certutil` is missing."
            )
            console.print(
                f"Please run [bold]'sudo {self._package_manager} install {package_name}'[/bold] "
                "to ensure browsers trust your certificates."
            )

        self._mkcert_path = MKCERT_PATH
        return self._mkcert_path

    def setup_ca(self) -> bool:
        """
        Runs `mkcert -install` to create a local Certificate Authority.

        Returns:
            True if the CA was installed successfully, False otherwise.
        """
        if not self._mkcert_path.exists():
            console.print(
                "[bold red]mkcert is not installed. Please run 'gantry setup' first.[/bold red]"
            )
            return False

        console.print("🔐 Setting up local Certificate Authority (CA)...")
        console.print("You might be prompted for your password.")

        try:
            result = subprocess.run(
                [str(self._mkcert_path), "-install"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                console.print(f"[bold red]Error installing local CA:[/bold red]")
                console.print(result.stderr)
                return False

            console.print(result.stdout)
            console.print(result.stderr, style="dim")
            console.print("\n✅ Local CA installed successfully.")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            console.print(f"[bold red]Failed to execute mkcert: {e}[/bold red]")
            return False

    def generate_cert(self, domains: list[str]) -> bool:
        """
        Generates a TLS certificate for the given domains.

        Args:
            domains: A list of domain names to include in the certificate.

        Returns:
            True if the certificate was generated successfully, False otherwise.
        """
        if not self._mkcert_path.exists():
            console.print(
                "[bold red]mkcert is not installed. Please run 'gantry setup' first.[/bold red]"
            )
            return False

        if not domains:
            console.print(
                "[bold red]No domains provided for certificate generation.[/bold red]"
            )
            return False

        CERTS_DIR.mkdir(parents=True, exist_ok=True)
        cert_name = domains[0].replace("*.", "wildcard.")
        cert_path = CERTS_DIR / f"{cert_name}.pem"
        key_path = CERTS_DIR / f"{cert_name}-key.pem"

        console.print(
            f"Generating certificate for: [bold cyan]{', '.join(domains)}[/bold cyan]"
        )
        command = [
            str(self._mkcert_path),
            "-cert-file",
            str(cert_path),
            "-key-file",
            str(key_path),
        ] + domains

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            console.print(result.stdout)
            console.print(result.stderr, style="dim")
            console.print(f"✅ Certificate and key saved to [cyan]{CERTS_DIR}[/cyan]")
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error generating certificate:[/bold red]")
            console.print(e.stderr)
            return False

    def get_ca_status(self) -> dict:
        """
        Checks the status of the mkcert local Certificate Authority.

        Returns:
            A dictionary with the installation status and the path to the CA file.
        """
        if not self._mkcert_path.exists():
            return {"installed": False, "path": None}

        try:
            result = subprocess.run(
                [str(self._mkcert_path), "-CAROOT"],
                capture_output=True,
                text=True,
                check=True,
            )
            ca_root = Path(result.stdout.strip())
            ca_path = ca_root / "rootCA.pem"
            return {
                "installed": ca_path.exists(),
                "path": str(ca_path) if ca_path.exists() else None,
            }
        except (subprocess.CalledProcessError, FileNotFoundError):
            return {"installed": False, "path": None}
