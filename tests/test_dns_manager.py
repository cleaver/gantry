"""Tests for DNS manager functionality."""

import socket
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from gantry.dns_manager import (
    DNSBackendNotFoundError,
    DNSConfigError,
    DNSManager,
    DNSManagerError,
    DNSTestError,
    GANTRY_DNS_CONFIG,
    DNSMASQ_CONFIG_DIR,
)
from gantry.dns_templates import DNSMASQ_CONFIG_TEMPLATE


@pytest.fixture
def dns_manager():
    """Create a DNSManager instance."""
    return DNSManager()


@pytest.fixture
def tmp_dns_config_dir(tmp_path, monkeypatch):
    """Create a temporary DNS config directory and patch the global constants."""
    config_dir = tmp_path / "dnsmasq.d"
    config_dir.mkdir()
    config_file = config_dir / "gantry.conf"

    # Patch the global constants
    monkeypatch.setattr("gantry.dns_manager.DNSMASQ_CONFIG_DIR", config_dir)
    monkeypatch.setattr("gantry.dns_manager.GANTRY_DNS_CONFIG", config_file)

    return config_dir, config_file


# ============================================================================
# DNS Manager Initialization Tests
# ============================================================================


class TestDNSManagerInitialization:
    """Test DNSManager initialization and basic state."""

    def test_dns_manager_initialization(self, dns_manager):
        """Test that DNSManager initializes with correct default state."""
        assert dns_manager._dnsmasq_installed is None
        assert dns_manager._dns_configured is None


# ============================================================================
# DNS Backend Detection Tests
# ============================================================================


class TestDNSBackendDetection:
    """Test dnsmasq detection and backend selection."""

    @patch("gantry.dns_manager.shutil.which")
    def test_detect_dns_backend_with_dnsmasq(self, mock_which, dns_manager):
        """Test detecting dnsmasq backend when installed."""
        mock_which.return_value = "/usr/sbin/dnsmasq"

        backend = dns_manager.detect_dns_backend()

        assert backend == "dnsmasq"
        mock_which.assert_called_once_with("dnsmasq")

    @patch("gantry.dns_manager.shutil.which")
    def test_detect_dns_backend_without_dnsmasq(self, mock_which, dns_manager):
        """Test detecting backend when dnsmasq is not installed."""
        mock_which.return_value = None

        with pytest.raises(DNSBackendNotFoundError) as exc_info:
            dns_manager.detect_dns_backend()

        assert "dnsmasq" in str(exc_info.value)
        mock_which.assert_called_once_with("dnsmasq")

    @patch("gantry.dns_manager.shutil.which")
    def test_check_dnsmasq_installed_true(self, mock_which, dns_manager):
        """Test checking dnsmasq installation when installed."""
        mock_which.return_value = "/usr/sbin/dnsmasq"

        result = dns_manager.check_dnsmasq_installed()

        assert result is True
        assert dns_manager._dnsmasq_installed is True

    @patch("gantry.dns_manager.shutil.which")
    def test_check_dnsmasq_installed_false(self, mock_which, dns_manager):
        """Test checking dnsmasq installation when not installed."""
        mock_which.return_value = None

        result = dns_manager.check_dnsmasq_installed()

        assert result is False
        assert dns_manager._dnsmasq_installed is False

    @patch("gantry.dns_manager.shutil.which")
    def test_check_dnsmasq_installed_caches_result(self, mock_which, dns_manager):
        """Test that dnsmasq installation check is cached."""
        mock_which.return_value = "/usr/sbin/dnsmasq"

        # First call
        result1 = dns_manager.check_dnsmasq_installed()

        # Second call should use cache
        result2 = dns_manager.check_dnsmasq_installed()

        assert result1 is True
        assert result2 is True
        # shutil.which should only be called once due to caching
        assert mock_which.call_count == 1


# ============================================================================
# Install Command Tests
# ============================================================================


class TestInstallCommand:
    """Test getting install commands for different distributions."""

    @patch("gantry.dns_manager.platform.system")
    @patch("builtins.open")
    def test_get_install_command_ubuntu(self, mock_open, mock_system, dns_manager):
        """Test getting install command for Ubuntu/Debian."""
        mock_system.return_value = "Linux"
        mock_file = MagicMock()
        mock_file.read.return_value = "ID=ubuntu\n"
        mock_file.__enter__.return_value = mock_file
        mock_open.return_value = mock_file

        command = dns_manager.get_install_command()

        assert command == "sudo apt-get update && sudo apt-get install -y dnsmasq"
        mock_open.assert_called_once_with("/etc/os-release", "r")

    @patch("gantry.dns_manager.platform.system")
    @patch("builtins.open")
    def test_get_install_command_fedora(self, mock_open, mock_system, dns_manager):
        """Test getting install command for Fedora/RHEL/CentOS."""
        mock_system.return_value = "Linux"
        mock_file = MagicMock()
        mock_file.read.return_value = "ID=fedora\n"
        mock_file.__enter__.return_value = mock_file
        mock_open.return_value = mock_file

        command = dns_manager.get_install_command()

        assert command == "sudo dnf install -y dnsmasq"

    @patch("gantry.dns_manager.platform.system")
    @patch("builtins.open")
    def test_get_install_command_arch(self, mock_open, mock_system, dns_manager):
        """Test getting install command for Arch/Manjaro."""
        mock_system.return_value = "Linux"
        mock_file = MagicMock()
        mock_file.read.return_value = "ID=manjaro\n"
        mock_file.__enter__.return_value = mock_file
        mock_open.return_value = mock_file

        command = dns_manager.get_install_command()

        assert command == "sudo pacman -S --noconfirm dnsmasq"

    @patch("gantry.dns_manager.platform.system")
    @patch("builtins.open")
    def test_get_install_command_opensuse(self, mock_open, mock_system, dns_manager):
        """Test getting install command for openSUSE."""
        mock_system.return_value = "Linux"
        mock_file = MagicMock()
        mock_file.read.return_value = "ID=opensuse\n"
        mock_file.__enter__.return_value = mock_file
        mock_open.return_value = mock_file

        command = dns_manager.get_install_command()

        assert command == "sudo zypper install -y dnsmasq"

    @patch("gantry.dns_manager.platform.system")
    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_get_install_command_no_os_release(
        self, mock_open, mock_system, dns_manager
    ):
        """Test getting install command when /etc/os-release doesn't exist."""
        mock_system.return_value = "Linux"

        command = dns_manager.get_install_command()

        assert command is None

    @patch("gantry.dns_manager.platform.system")
    def test_get_install_command_non_linux(self, mock_system, dns_manager):
        """Test getting install command on non-Linux systems."""
        mock_system.return_value = "Darwin"

        command = dns_manager.get_install_command()

        assert command is None


# ============================================================================
# DNS Config Generation Tests
# ============================================================================


class TestDNSConfigGeneration:
    """Test dnsmasq config generation."""

    def test_generate_dnsmasq_config(self, dns_manager):
        """Test that config generation returns correct template."""
        config = dns_manager._generate_dnsmasq_config()

        # Verify config matches template
        assert config == DNSMASQ_CONFIG_TEMPLATE

        # Verify config contains required elements
        assert "# /etc/dnsmasq.d/gantry.conf (generated)" in config
        assert "# Auto-generated by Gantry" in config
        assert "# Do not edit manually; changes will be overwritten" in config
        assert "address=/.test/127.0.0.1" in config

    def test_generate_dnsmasq_config_format(self, dns_manager):
        """Test that generated config has correct format."""
        config = dns_manager._generate_dnsmasq_config()

        # Config should end with newline
        assert config.endswith("\n")

        # Should have proper dnsmasq syntax
        lines = config.strip().split("\n")
        assert any("address=/.test/127.0.0.1" in line for line in lines)


# ============================================================================
# DNS Setup Tests (with mocked system calls)
# ============================================================================


class TestDNSSetup:
    """Test DNS setup with mocked system calls."""

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    def test_setup_dns_success_with_sudo(
        self, mock_subprocess, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test successful DNS setup with sudo."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"

        # Mock successful subprocess calls
        mock_subprocess.return_value = MagicMock(returncode=0)

        result = dns_manager.setup_dns(require_sudo=True)

        assert result is True
        assert dns_manager._dns_configured is True

        # Verify subprocess was called for tee and chmod
        assert mock_subprocess.call_count >= 2

        # Check that tee was called with correct arguments
        tee_call = None
        for call in mock_subprocess.call_args_list:
            if call[0][0][0] == "sudo" and call[0][0][1] == "tee":
                tee_call = call
                break

        assert tee_call is not None
        assert str(config_file) in tee_call[0][0]
        assert tee_call[1]["input"] == dns_manager._generate_dnsmasq_config()
        assert tee_call[1]["text"] is True
        assert tee_call[1]["capture_output"] is True
        assert tee_call[1]["check"] is True

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    @patch("gantry.dns_manager.platform.system")
    def test_setup_dns_success_without_sudo(
        self, mock_system, mock_subprocess, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test successful DNS setup without sudo (direct write)."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"
        mock_system.return_value = "Linux"
        mock_subprocess.return_value = MagicMock(returncode=0)

        result = dns_manager.setup_dns(require_sudo=False)

        assert result is True
        assert dns_manager._dns_configured is True

        # Verify config file was written directly
        assert config_file.exists()
        assert config_file.read_text() == dns_manager._generate_dnsmasq_config()

    @patch("gantry.dns_manager.shutil.which")
    def test_setup_dns_fails_when_dnsmasq_not_installed(self, mock_which, dns_manager):
        """Test that setup_dns raises error when dnsmasq is not installed."""
        mock_which.return_value = None

        with pytest.raises(DNSBackendNotFoundError) as exc_info:
            dns_manager.setup_dns()

        assert "dnsmasq is not installed" in str(exc_info.value)

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    def test_setup_dns_fails_on_config_write_error(
        self, mock_subprocess, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test that setup_dns raises error when config write fails."""
        mock_which.return_value = "/usr/sbin/dnsmasq"

        # Mock subprocess failure for tee
        mock_subprocess.side_effect = [
            subprocess.CalledProcessError(1, "sudo", stderr="Permission denied"),
        ]

        with pytest.raises(DNSConfigError) as exc_info:
            dns_manager.setup_dns(require_sudo=True)

        assert "Failed to write DNS configuration" in str(exc_info.value)

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    @patch("gantry.dns_manager.platform.system")
    def test_setup_dns_fails_on_service_restart_error(
        self, mock_system, mock_subprocess, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test that setup_dns raises error when service restart fails."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"
        mock_system.return_value = "Linux"

        # Mock successful tee/chmod, but failed restart
        mock_subprocess.side_effect = [
            MagicMock(returncode=0),  # tee
            MagicMock(returncode=0),  # chmod
            subprocess.CalledProcessError(
                1, "sudo", stderr="Service failed"
            ),  # systemctl
            subprocess.CalledProcessError(
                1, "sudo", stderr="Service failed"
            ),  # service fallback
        ]

        with pytest.raises(DNSConfigError) as exc_info:
            dns_manager.setup_dns(require_sudo=True)

        assert "Could not restart dnsmasq" in str(
            exc_info.value
        ) or "Failed to restart dnsmasq" in str(exc_info.value)

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    @patch("gantry.dns_manager.platform.system")
    def test_restart_dnsmasq_uses_systemctl(
        self, mock_system, mock_subprocess, mock_which, dns_manager
    ):
        """Test that restart uses systemctl when available."""
        mock_which.return_value = "/usr/sbin/dnsmasq"
        mock_system.return_value = "Linux"
        mock_subprocess.return_value = MagicMock(returncode=0)

        dns_manager.setup_dns(require_sudo=True)

        # Find systemctl restart call
        systemctl_calls = [
            call
            for call in mock_subprocess.call_args_list
            if len(call[0][0]) >= 3 and call[0][0][1] == "systemctl"
        ]
        assert len(systemctl_calls) > 0

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    @patch("gantry.dns_manager.platform.system")
    def test_restart_dnsmasq_falls_back_to_service(
        self, mock_system, mock_subprocess, mock_which, dns_manager
    ):
        """Test that restart falls back to service command if systemctl fails."""
        mock_which.return_value = "/usr/sbin/dnsmasq"
        mock_system.return_value = "Linux"

        # Mock systemctl failure, service success
        mock_subprocess.side_effect = [
            MagicMock(returncode=0),  # tee
            MagicMock(returncode=0),  # chmod
            subprocess.CalledProcessError(1, "sudo"),  # systemctl fails
            MagicMock(returncode=0),  # service succeeds
        ]

        result = dns_manager.setup_dns(require_sudo=True)

        assert result is True

        # Verify service command was called
        service_calls = [
            call
            for call in mock_subprocess.call_args_list
            if len(call[0][0]) >= 2 and call[0][0][1] == "service"
        ]
        assert len(service_calls) > 0


# ============================================================================
# DNS Registration Tests
# ============================================================================


class TestDNSRegistration:
    """Test DNS registration and unregistration."""

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    def test_register_dns_success(
        self, mock_subprocess, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test successful DNS registration."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"
        mock_subprocess.return_value = MagicMock(returncode=0)

        # Setup DNS first
        dns_manager.setup_dns(require_sudo=False)

        # Register DNS
        result = dns_manager.register_dns("testproject")

        assert result is True

    @patch("gantry.dns_manager.shutil.which")
    def test_register_dns_fails_when_not_configured(
        self, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test that register_dns fails when DNS is not configured."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"

        # Don't setup DNS

        with pytest.raises(DNSConfigError) as exc_info:
            dns_manager.register_dns("testproject")

        assert "DNS is not configured" in str(exc_info.value)

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    def test_unregister_dns_success(
        self, mock_subprocess, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test successful DNS unregistration."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"
        mock_subprocess.return_value = MagicMock(returncode=0)

        # Setup DNS first
        dns_manager.setup_dns(require_sudo=False)

        # Unregister DNS (should always succeed with wildcard config)
        result = dns_manager.unregister_dns("testproject")

        assert result is True


# ============================================================================
# DNS Configuration Status Tests
# ============================================================================


class TestDNSConfigurationStatus:
    """Test checking DNS configuration status."""

    @patch("gantry.dns_manager.shutil.which")
    def test_is_dns_configured_false_when_file_missing(
        self, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test that _is_dns_configured returns False when config file doesn't exist."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"

        # Config file doesn't exist
        assert not config_file.exists()

        result = dns_manager._is_dns_configured()

        assert result is False
        assert dns_manager._dns_configured is False

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    def test_is_dns_configured_true_when_file_exists_with_correct_content(
        self, mock_subprocess, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test that _is_dns_configured returns True when config file has correct content."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"
        mock_subprocess.return_value = MagicMock(returncode=0)

        # Setup DNS to create config file
        dns_manager.setup_dns(require_sudo=False)

        # Reset the cached state
        dns_manager._dns_configured = None

        result = dns_manager._is_dns_configured()

        assert result is True
        assert dns_manager._dns_configured is True

    @patch("gantry.dns_manager.shutil.which")
    def test_is_dns_configured_false_when_file_has_wrong_content(
        self, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test that _is_dns_configured returns False when config file has wrong content."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"

        # Write incorrect content
        config_file.write_text("# Wrong config\naddress=/wrong/192.168.1.1\n")

        result = dns_manager._is_dns_configured()

        assert result is False
        assert dns_manager._dns_configured is False

    @patch("gantry.dns_manager.shutil.which")
    @patch("gantry.dns_manager.subprocess.run")
    def test_get_dns_status(
        self, mock_subprocess, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test getting DNS status information."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"
        mock_subprocess.return_value = MagicMock(returncode=0)

        dns_manager.setup_dns(require_sudo=False)

        status = dns_manager.get_dns_status()

        assert status["dnsmasq_installed"] is True
        assert status["dns_configured"] is True
        assert status["config_file"] == str(config_file)
        assert status["config_exists"] is True
        assert status["backend"] == "dnsmasq"

    @patch("gantry.dns_manager.shutil.which")
    def test_get_dns_status_when_not_configured(
        self, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test getting DNS status when not configured."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = "/usr/sbin/dnsmasq"

        status = dns_manager.get_dns_status()

        assert status["dnsmasq_installed"] is True
        assert status["dns_configured"] is False
        assert status["config_exists"] is False
        assert status["backend"] == "dnsmasq"

    @patch("gantry.dns_manager.shutil.which")
    def test_get_dns_status_when_dnsmasq_not_installed(
        self, mock_which, dns_manager, tmp_dns_config_dir
    ):
        """Test getting DNS status when dnsmasq is not installed."""
        config_dir, config_file = tmp_dns_config_dir
        mock_which.return_value = None

        status = dns_manager.get_dns_status()

        assert status["dnsmasq_installed"] is False
        assert status["dns_configured"] is False
        assert status["backend"] is None


# ============================================================================
# DNS Resolution Verification Tests
# ============================================================================


class TestDNSResolutionVerification:
    """Test DNS resolution verification."""

    @patch("socket.gethostbyname")
    def test_test_dns_success_with_hostname(self, mock_gethostbyname, dns_manager):
        """Test successful DNS resolution with hostname (without .test suffix)."""
        mock_gethostbyname.return_value = "127.0.0.1"

        result = dns_manager.test_dns("testproject")

        assert result is True
        mock_gethostbyname.assert_called_once_with("testproject.test")

    @patch("socket.gethostbyname")
    def test_test_dns_success_with_full_hostname(self, mock_gethostbyname, dns_manager):
        """Test successful DNS resolution with full hostname (with .test suffix)."""
        mock_gethostbyname.return_value = "127.0.0.1"

        result = dns_manager.test_dns("testproject.test")

        assert result is True
        mock_gethostbyname.assert_called_once_with("testproject.test")

    @patch("socket.gethostbyname")
    def test_test_dns_fails_with_wrong_ip(self, mock_gethostbyname, dns_manager):
        """Test that test_dns fails when wrong IP is returned."""
        mock_gethostbyname.return_value = "192.168.1.1"

        with pytest.raises(DNSTestError) as exc_info:
            dns_manager.test_dns("testproject")

        assert "returned 192.168.1.1" in str(exc_info.value)
        assert "expected 127.0.0.1" in str(exc_info.value)
        mock_gethostbyname.assert_called_once_with("testproject.test")

    @patch("socket.gethostbyname")
    def test_test_dns_fails_with_resolution_error(
        self, mock_gethostbyname, dns_manager
    ):
        """Test that test_dns fails when DNS resolution fails."""
        mock_gethostbyname.side_effect = socket.gaierror("Name or service not known")

        with pytest.raises(DNSTestError) as exc_info:
            dns_manager.test_dns("testproject")

        assert "DNS resolution failed" in str(exc_info.value)
        assert "testproject.test" in str(exc_info.value)
        mock_gethostbyname.assert_called_once_with("testproject.test")

    @patch("socket.gethostbyname")
    def test_test_dns_fails_with_unexpected_error(
        self, mock_gethostbyname, dns_manager
    ):
        """Test that test_dns handles unexpected errors."""
        mock_gethostbyname.side_effect = ValueError("Unexpected error")

        with pytest.raises(DNSTestError) as exc_info:
            dns_manager.test_dns("testproject")

        assert "Unexpected error testing DNS" in str(exc_info.value)
        assert "testproject.test" in str(exc_info.value)
        mock_gethostbyname.assert_called_once_with("testproject.test")

    @patch("socket.gethostbyname")
    def test_test_dns_with_various_hostnames(self, mock_gethostbyname, dns_manager):
        """Test DNS resolution with various hostname formats."""
        mock_gethostbyname.return_value = "127.0.0.1"

        test_cases = [
            "simple",
            "with-dashes",
            "with_underscores",
            "MixedCase",
            "123numeric",
        ]

        for hostname in test_cases:
            result = dns_manager.test_dns(hostname)
            assert result is True

        # Verify all were called with .test suffix
        assert mock_gethostbyname.call_count == len(test_cases)
        for call in mock_gethostbyname.call_args_list:
            assert call[0][0].endswith(".test")
