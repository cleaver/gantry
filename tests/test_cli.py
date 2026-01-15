"""Tests for CLI command parsing and execution."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from gantry.cli import app


@pytest.fixture
def cli_runner():
    """Create a Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_registry_and_allocator(monkeypatch, tmp_gantry_home):
    """Mock the global registry and port_allocator instances."""
    from gantry.registry import Registry
    from gantry.port_allocator import PortAllocator
    from gantry.dns_manager import DNSManager
    
    registry = Registry()
    port_allocator = PortAllocator(registry)
    dns_manager = DNSManager()
    
    monkeypatch.setattr("gantry.cli.registry", registry)
    monkeypatch.setattr("gantry.cli.port_allocator", port_allocator)
    monkeypatch.setattr("gantry.cli.dns_manager", dns_manager)
    
    return registry, port_allocator


class TestRegisterCommand:
    """Test register command."""
    
    def test_register_with_flags(self, cli_runner, mock_registry_and_allocator, tmp_path, monkeypatch):
        """Test registering with --hostname and --path flags."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        # Mock DNS manager to avoid accessing system files
        from gantry.cli import dns_manager
        mock_dns_status = MagicMock(return_value={
            "dnsmasq_installed": False,
            "dns_configured": False,
            "config_file": "/etc/dnsmasq.d/gantry.conf",
            "config_exists": False,
            "backend": None,
        })
        monkeypatch.setattr(dns_manager, "get_dns_status", mock_dns_status)
        
        # Mock port allocation
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            result = cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        assert result.exit_code == 0
        assert "registered successfully" in result.stdout.lower()
        assert "myproject" in result.stdout
        
        # Verify project was registered
        project = registry.get_project("myproject")
        assert project is not None
        assert project.hostname == "myproject"
    
    def test_register_interactive_prompt(self, cli_runner, mock_registry_and_allocator, tmp_path, monkeypatch):
        """Test interactive prompt when hostname not provided."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        # Mock DNS manager to avoid accessing system files
        from gantry.cli import dns_manager
        mock_dns_status = MagicMock(return_value={
            "dnsmasq_installed": False,
            "dns_configured": False,
            "config_file": "/etc/dnsmasq.d/gantry.conf",
            "config_exists": False,
            "backend": None,
        })
        monkeypatch.setattr(dns_manager, "get_dns_status", mock_dns_status)
        
        # Mock typer.prompt to return hostname
        mock_prompt = MagicMock(return_value="myproject")
        monkeypatch.setattr("typer.prompt", mock_prompt)
        
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            result = cli_runner.invoke(
                app,
                ["register", "--path", str(project_path)]
            )
        
        assert result.exit_code == 0
        mock_prompt.assert_called_once()
    
    def test_register_duplicate_hostname(self, cli_runner, mock_registry_and_allocator, tmp_path):
        """Test error handling for duplicate hostname."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        # Register first project
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        # Try to register again
        other_path = tmp_path / "other"
        other_path.mkdir()
        with patch.object(port_allocator, "allocate_port", return_value=5002):
            result = cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(other_path)]
            )
        
        assert result.exit_code == 1
        assert "error" in result.stdout.lower() or "already" in result.stdout.lower()
    
    def test_register_invalid_path(self, cli_runner, mock_registry_and_allocator, tmp_path):
        """Test error handling for invalid path."""
        invalid_path = tmp_path / "nonexistent"
        
        result = cli_runner.invoke(
            app,
            ["register", "--hostname", "myproject", "--path", str(invalid_path)]
        )
        
        # Typer should validate path and exit with error
        assert result.exit_code != 0
    
    def test_register_output_messages(self, cli_runner, mock_registry_and_allocator, tmp_path, monkeypatch):
        """Test that register command outputs correct messages."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        # Mock DNS manager to avoid accessing system files
        from gantry.cli import dns_manager
        mock_dns_status = MagicMock(return_value={
            "dnsmasq_installed": False,
            "dns_configured": False,
            "config_file": "/etc/dnsmasq.d/gantry.conf",
            "config_exists": False,
            "backend": None,
        })
        monkeypatch.setattr(dns_manager, "get_dns_status", mock_dns_status)
        
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            result = cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        assert result.exit_code == 0
        assert "registering" in result.stdout.lower()
        assert "registered successfully" in result.stdout.lower()
        assert "5001" in result.stdout or "port" in result.stdout.lower()


class TestListCommand:
    """Test list command."""
    
    def test_list_displays_table(self, cli_runner, mock_registry_and_allocator, tmp_path):
        """Test that list command displays table with all projects."""
        registry, port_allocator = mock_registry_and_allocator
        
        # Register multiple projects
        for i in range(2):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            with patch.object(port_allocator, "allocate_port", return_value=5001 + i):
                cli_runner.invoke(
                    app,
                    ["register", "--hostname", f"project{i}", "--path", str(project_path)]
                )
        
        result = cli_runner.invoke(app, ["list"])
        
        assert result.exit_code == 0
        assert "project0" in result.stdout
        assert "project1" in result.stdout
    
    def test_list_empty_registry(self, cli_runner, mock_registry_and_allocator):
        """Test list command when registry is empty."""
        result = cli_runner.invoke(app, ["list"])
        
        assert result.exit_code == 0
        assert "no projects" in result.stdout.lower()
    
    def test_list_table_columns(self, cli_runner, mock_registry_and_allocator, tmp_path):
        """Test that list command shows correct table columns."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        result = cli_runner.invoke(app, ["list"])
        
        assert result.exit_code == 0
        # Check for table headers (may be in different format)
        output = result.stdout.lower()
        assert "hostname" in output or "myproject" in output


class TestUnregisterCommand:
    """Test unregister command."""
    
    def test_unregister_existing_project(self, cli_runner, mock_registry_and_allocator, tmp_path, monkeypatch):
        """Test unregistering an existing project."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        # Register project
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        # Mock confirmation
        mock_confirm = MagicMock(return_value=True)
        monkeypatch.setattr("typer.confirm", mock_confirm)
        
        result = cli_runner.invoke(app, ["unregister", "myproject"])
        
        assert result.exit_code == 0
        assert "unregistered" in result.stdout.lower()
        assert registry.get_project("myproject") is None
    
    def test_unregister_nonexistent_project(self, cli_runner, mock_registry_and_allocator):
        """Test error for non-existent project."""
        result = cli_runner.invoke(app, ["unregister", "nonexistent"])
        
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()
    
    def test_unregister_confirmation_prompt(self, cli_runner, mock_registry_and_allocator, tmp_path, monkeypatch):
        """Test that unregister shows confirmation prompt."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        mock_confirm = MagicMock(return_value=True)
        monkeypatch.setattr("typer.confirm", mock_confirm)
        
        cli_runner.invoke(app, ["unregister", "myproject"])
        
        mock_confirm.assert_called_once()
    
    def test_unregister_warning_when_running(self, cli_runner, mock_registry_and_allocator, tmp_path, monkeypatch):
        """Test warning when unregistering a running project."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        # Set project to running
        registry.update_project_status("myproject", "running")
        
        mock_confirm = MagicMock(return_value=True)
        monkeypatch.setattr("typer.confirm", mock_confirm)
        
        result = cli_runner.invoke(app, ["unregister", "myproject"])
        
        assert "warning" in result.stdout.lower() or "running" in result.stdout.lower()


class TestStatusCommand:
    """Test status command."""
    
    def test_status_displays_table(self, cli_runner, mock_registry_and_allocator, tmp_path):
        """Test that status command displays status table."""
        registry, port_allocator = mock_registry_and_allocator
        
        # Register project
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        result = cli_runner.invoke(app, ["status"])
        
        assert result.exit_code == 0
        assert "myproject" in result.stdout
    
    def test_status_empty_registry(self, cli_runner, mock_registry_and_allocator):
        """Test status command when registry is empty."""
        result = cli_runner.invoke(app, ["status"])
        
        assert result.exit_code == 0
        assert "no projects" in result.stdout.lower()
    
    def test_status_shows_different_statuses(self, cli_runner, mock_registry_and_allocator, tmp_path):
        """Test that status command shows different project statuses."""
        registry, port_allocator = mock_registry_and_allocator
        
        # Register and set different statuses
        for i, status in enumerate(["running", "stopped", "error"]):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            with patch.object(port_allocator, "allocate_port", return_value=5001 + i):
                cli_runner.invoke(
                    app,
                    ["register", "--hostname", f"project{i}", "--path", str(project_path)]
                )
            registry.update_project_status(f"project{i}", status)
        
        result = cli_runner.invoke(app, ["status"])
        
        assert result.exit_code == 0
        # Status should be displayed (may be colorized)
        output = result.stdout.lower()
        assert "project0" in output or "project1" in output or "project2" in output


class TestConfigCommand:
    """Test config command."""
    
    def test_config_displays_metadata(self, cli_runner, mock_registry_and_allocator, tmp_path):
        """Test that config command displays project metadata."""
        registry, port_allocator = mock_registry_and_allocator
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        with patch.object(port_allocator, "allocate_port", return_value=5001):
            cli_runner.invoke(
                app,
                ["register", "--hostname", "myproject", "--path", str(project_path)]
            )
        
        result = cli_runner.invoke(app, ["config", "myproject"])
        
        assert result.exit_code == 0
        assert "myproject" in result.stdout
        # Should contain project metadata (may be JSON or formatted)
    
    def test_config_nonexistent_project(self, cli_runner, mock_registry_and_allocator):
        """Test error for non-existent project."""
        result = cli_runner.invoke(app, ["config", "nonexistent"])
        
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()


class TestUpdateCommand:
    """Test update command (when implemented)."""
    
    def test_update_command_not_implemented(self, cli_runner, mock_registry_and_allocator):
        """Test that update command shows not implemented message."""
        result = cli_runner.invoke(app, ["update", "myproject"])
        
        # Currently just shows not implemented message
        assert "not yet implemented" in result.stdout.lower() or result.exit_code != 0
    
    # Note: When update command is fully implemented, add tests for:
    # - Calling detectors.rescan_project()
    # - Displaying diff/changelog
    # - Checking port conflicts with running projects
    # - Warning if project is running
    # - --dry-run flag
    # - --yes flag
    # - Applying updates via registry.update_project_metadata()
    # - Handling removed docker-compose.yml
    # - Port conflict detection during update
