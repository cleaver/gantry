"""DNS management for .test domain resolution using dnsmasq."""

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# DNS configuration paths
DNSMASQ_CONFIG_DIR = Path("/etc/dnsmasq.d")
GANTRY_DNS_CONFIG = DNSMASQ_CONFIG_DIR / "gantry.conf"
RESOLV_CONF = Path("/etc/resolv.conf")


# --- Custom Exceptions ---


class DNSManagerError(Exception):
    """Base exception for DNS manager errors."""

    pass


class DNSBackendNotFoundError(DNSManagerError):
    """Raised when dnsmasq is not found."""

    pass


class DNSConfigError(DNSManagerError):
    """Raised when DNS configuration fails."""

    pass


class DNSTestError(DNSManagerError):
    """Raised when DNS resolution test fails."""

    pass


# --- DNS Manager ---


class DNSManager:
    """Manages DNS configuration for .test domain resolution."""

    def __init__(self):
        self._dnsmasq_installed = None
        self._dns_configured = None

    def detect_dns_backend(self) -> str:
        """
        Detect available DNS backend.

        Returns:
            Backend name (currently only 'dnsmasq' is supported)

        Raises:
            DNSBackendNotFoundError: If no supported backend is found
        """
        # Check for dnsmasq
        if self._is_dnsmasq_installed():
            return "dnsmasq"

        raise DNSBackendNotFoundError(
            "No supported DNS backend found. dnsmasq is required for .test domain resolution."
        )

    def _is_dnsmasq_installed(self) -> bool:
        """Check if dnsmasq is installed."""
        if self._dnsmasq_installed is not None:
            return self._dnsmasq_installed

        # Check if dnsmasq command exists
        dnsmasq_path = shutil.which("dnsmasq")
        self._dnsmasq_installed = dnsmasq_path is not None

        return self._dnsmasq_installed

    def check_dnsmasq_installed(self) -> bool:
        """
        Check if dnsmasq is installed.

        Returns:
            True if dnsmasq is installed, False otherwise
        """
        return self._is_dnsmasq_installed()

    def get_install_command(self) -> Optional[str]:
        """
        Get the package manager command to install dnsmasq.

        Returns:
            Installation command string, or None if package manager not detected
        """
        system = platform.system().lower()

        if system == "linux":
            # Detect Linux distribution
            try:
                with open("/etc/os-release", "r") as f:
                    os_release = f.read().lower()

                    if "ubuntu" in os_release or "debian" in os_release:
                        return "sudo apt-get update && sudo apt-get install -y dnsmasq"
                    elif (
                        "fedora" in os_release
                        or "rhel" in os_release
                        or "centos" in os_release
                    ):
                        return "sudo dnf install -y dnsmasq"
                    elif "arch" in os_release or "manjaro" in os_release:
                        return "sudo pacman -S --noconfirm dnsmasq"
                    elif "opensuse" in os_release or "suse" in os_release:
                        return "sudo zypper install -y dnsmasq"
            except (FileNotFoundError, PermissionError):
                pass

        return None

    def setup_dns(self, require_sudo: bool = True) -> bool:
        """
        Set up DNS configuration for .test domain resolution.

        This creates the dnsmasq configuration file and restarts dnsmasq.
        Requires sudo privileges.

        Args:
            require_sudo: If True, will attempt to use sudo for privileged operations

        Returns:
            True if setup was successful

        Raises:
            DNSBackendNotFoundError: If dnsmasq is not installed
            DNSConfigError: If configuration fails
        """
        # Check if dnsmasq is installed
        if not self._is_dnsmasq_installed():
            raise DNSBackendNotFoundError(
                "dnsmasq is not installed. Install it with your package manager:\n"
                f"  {self.get_install_command() or 'See your distribution documentation'}"
            )

        # Generate dnsmasq configuration
        config_content = self._generate_dnsmasq_config()

        # Write configuration file (requires sudo)
        try:
            if require_sudo:
                self._write_config_with_sudo(config_content)
            else:
                self._write_config_direct(config_content)
        except subprocess.CalledProcessError as e:
            raise DNSConfigError(
                f"Failed to write DNS configuration: {e.stderr or str(e)}"
            ) from e
        except PermissionError as e:
            raise DNSConfigError(
                f"Permission denied writing DNS configuration. "
                f"Run with sudo or ensure you have write access to {DNSMASQ_CONFIG_DIR}"
            ) from e

        # Restart dnsmasq to apply configuration
        try:
            self._restart_dnsmasq(require_sudo=require_sudo)
        except subprocess.CalledProcessError as e:
            raise DNSConfigError(
                f"Failed to restart dnsmasq: {e.stderr or str(e)}"
            ) from e

        self._dns_configured = True
        return True

    def _generate_dnsmasq_config(self) -> str:
        """Generate dnsmasq configuration content."""
        return """# /etc/dnsmasq.d/gantry.conf (generated)
# Auto-generated by Gantry
# Do not edit manually; changes will be overwritten

address=/.test/127.0.0.1
"""

    def _write_config_with_sudo(self, content: str) -> None:
        """Write configuration file using sudo."""
        # Ensure the directory exists before writing (tee cannot create parent directories)
        subprocess.run(
            ["sudo", "mkdir", "-p", str(DNSMASQ_CONFIG_DIR)],
            check=True,
            capture_output=True,
        )

        # Use tee to write with sudo
        subprocess.run(
            ["sudo", "tee", str(GANTRY_DNS_CONFIG)],
            input=content,
            text=True,
            capture_output=True,
            check=True,
        )

        # Set proper permissions
        subprocess.run(
            ["sudo", "chmod", "644", str(GANTRY_DNS_CONFIG)],
            check=True,
            capture_output=True,
        )

    def _write_config_direct(self, content: str) -> None:
        """Write configuration file directly (requires root privileges)."""
        # Ensure directory exists
        DNSMASQ_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Write file
        GANTRY_DNS_CONFIG.write_text(content)
        GANTRY_DNS_CONFIG.chmod(0o644)

    def _restart_dnsmasq(self, require_sudo: bool = True) -> None:
        """Restart dnsmasq service."""
        system = platform.system().lower()

        if system == "linux":
            # Try systemd first (most common)
            try:
                if require_sudo:
                    subprocess.run(
                        ["sudo", "systemctl", "restart", "dnsmasq"],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                else:
                    subprocess.run(
                        ["systemctl", "restart", "dnsmasq"],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                return
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

            # Fallback: try service command
            try:
                if require_sudo:
                    subprocess.run(
                        ["sudo", "service", "dnsmasq", "restart"],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                else:
                    subprocess.run(
                        ["service", "dnsmasq", "restart"],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                return
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

        # If we get here, we couldn't restart the service
        raise DNSConfigError(
            "Could not restart dnsmasq service. "
            "Please restart it manually: sudo systemctl restart dnsmasq"
        )

    def register_dns(self, hostname: str) -> bool:
        """
        Register DNS entry for a hostname.

        Note: With the wildcard configuration (address=/.test/127.0.0.1),
        all .test domains automatically resolve to 127.0.0.1, so individual
        registration is not strictly necessary. This method exists for
        potential future use or explicit registration.

        Args:
            hostname: Hostname to register (e.g., 'proj1' for 'proj1.test')

        Returns:
            True if registration was successful (always True with wildcard config)
        """
        # With wildcard DNS configuration, all .test domains automatically resolve
        # No explicit registration needed, but we verify DNS is configured
        if not self._is_dns_configured():
            raise DNSConfigError("DNS is not configured. Run 'gantry dns-setup' first.")

        return True

    def unregister_dns(self, hostname: str) -> bool:
        """
        Unregister DNS entry for a hostname.

        Note: With wildcard configuration, individual unregistration is not
        possible. This method exists for API consistency.

        Args:
            hostname: Hostname to unregister

        Returns:
            True if unregistration was successful
        """
        # With wildcard DNS, we can't unregister individual hostnames
        # This is a no-op but maintains API consistency
        return True

    def _is_dns_configured(self) -> bool:
        """Check if DNS is configured."""
        if self._dns_configured is not None:
            return self._dns_configured

        # Check if config file exists
        if not GANTRY_DNS_CONFIG.exists():
            self._dns_configured = False
            return False

        # Check if config file has correct content
        try:
            content = GANTRY_DNS_CONFIG.read_text()
            if "address=/.test/127.0.0.1" in content:
                self._dns_configured = True
                return True
        except (PermissionError, IOError):
            pass

        self._dns_configured = False
        return False

    def test_dns(self, hostname: str) -> bool:
        """
        Test DNS resolution for a hostname.

        Args:
            hostname: Hostname to test (e.g., 'proj1' for 'proj1.test')

        Returns:
            True if DNS resolution works

        Raises:
            DNSTestError: If DNS resolution fails
        """
        import socket

        # Ensure hostname doesn't already have .test suffix
        if hostname.endswith(".test"):
            test_hostname = hostname
        else:
            test_hostname = f"{hostname}.test"

        try:
            # Try to resolve the hostname
            ip_address = socket.gethostbyname(test_hostname)

            # Verify it resolves to 127.0.0.1
            if ip_address == "127.0.0.1":
                return True
            else:
                raise DNSTestError(
                    f"DNS resolution for {test_hostname} returned {ip_address}, "
                    f"expected 127.0.0.1"
                )
        except socket.gaierror as e:
            raise DNSTestError(f"DNS resolution failed for {test_hostname}: {e}") from e
        except Exception as e:
            raise DNSTestError(
                f"Unexpected error testing DNS for {test_hostname}: {e}"
            ) from e

    def get_dns_status(self) -> dict:
        """
        Get current DNS configuration status.

        Returns:
            Dictionary with status information
        """
        dnsmasq_installed = self._is_dnsmasq_installed()
        dns_configured = self._is_dns_configured()
        backend = None
        if dnsmasq_installed:
            try:
                backend = self.detect_dns_backend()
            except DNSBackendNotFoundError:
                # If dnsmasq check passed but detect fails, backend is None
                pass
        return {
            "dnsmasq_installed": dnsmasq_installed,
            "dns_configured": dns_configured,
            "config_file": str(GANTRY_DNS_CONFIG),
            "config_exists": GANTRY_DNS_CONFIG.exists(),
            "backend": backend,
        }
