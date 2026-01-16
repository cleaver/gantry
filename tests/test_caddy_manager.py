import subprocess
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from gantry.caddy_manager import (
    CADDY_CONFIG_DIR,
    CADDY_CONFIG_PATH,
    CaddyCommandError,
    CaddyManager,
    CaddyMissingError,
    get_caddy_path,
)
from gantry.registry import Project, Registry


@pytest.fixture
def mock_registry():
    """Fixture to create a mock registry with some projects."""
    registry = MagicMock(spec=Registry)
    projects = [
        Project(
            hostname="proj1",
            path=Path("/tmp/proj1"),
            port=5001,
            service_ports={"db": 5002, "mail": 1025},
            exposed_ports=[5001, 5002, 1025],
            services=["web", "db", "mail"],
            docker_compose=True,
            status="stopped",
            working_directory=Path("/tmp/proj1"),
            environment_vars={},
            registered_at="2023-01-01T12:00:00Z",
            last_started=None,
            last_updated="2023-01-01T12:00:00Z"
        ),
        Project(
            hostname="proj2",
            path=Path("/tmp/proj2"),
            port=5003,
            service_ports={},
            exposed_ports=[5003],
            services=["app"],
            docker_compose=False,
            status="stopped",
            working_directory=Path("/tmp/proj2"),
            environment_vars={},
            registered_at="2023-01-01T12:00:00Z",
            last_started=None,
            last_updated="2023-01-01T12:00:00Z"
        ),
    ]
    registry.list_projects.return_value = projects
    return registry


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_caddy_manager_init(mock_get_path):
    """Test that CaddyManager initializes correctly."""
    registry = MagicMock(spec=Registry)
    with patch.object(Path, "mkdir") as mock_mkdir:
        manager = CaddyManager(registry)
        assert manager._registry is registry
        assert manager._caddy_path == Path("/fake/caddy")
        mock_get_path.assert_called_once()
        mock_mkdir.assert_called_once_with(exist_ok=True)


def test_get_caddy_path_missing():
    """Test that get_caddy_path raises an error if Caddy is not found."""
    with patch("gantry.caddy_manager.check_caddy_installed", return_value=None):
        with pytest.raises(CaddyMissingError, match="Caddy binary not found"):
            get_caddy_path()


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_generate_caddyfile(mock_get_path, mock_registry):
    """Test the generation of the Caddyfile."""
    manager = CaddyManager(mock_registry)
    
    m = mock_open()
    with patch("pathlib.Path.write_text", m):
        caddyfile = manager.generate_caddyfile()

        # Check that the file was written to
        m.assert_called_once_with(caddyfile)
        
        # Check the content of the generated Caddyfile
        assert "proj1.test" in caddyfile
        assert "reverse_proxy localhost:5001" in caddyfile
        assert "db.proj1.test" in caddyfile
        assert "reverse_proxy localhost:5002" in caddyfile
        assert "mail.proj1.test" in caddyfile
        assert "reverse_proxy localhost:1025" in caddyfile
        
        assert "proj2.test" in caddyfile
        assert "reverse_proxy localhost:5003" in caddyfile


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
@patch("subprocess.run")
def test_caddy_manager_run_command(mock_run, mock_get_path, mock_registry):
    """Test the internal _run_command method."""
    manager = CaddyManager(mock_registry)
    
    # Test successful command
    mock_run.return_value = MagicMock(check_returncode=lambda: None)
    manager._run_command(["status"])
    mock_run.assert_called_with(
        ["/fake/caddy", "status"],
        capture_output=True,
        text=True,
        check=True,
        cwd=CADDY_CONFIG_DIR
    )

    # Test command failure
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd", stderr="some error")
    with pytest.raises(CaddyCommandError, match="Caddy command failed: some error"):
        manager._run_command(["status"])


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_caddy_manager_start(mock_get_path, mock_registry):
    """Test starting Caddy."""
    manager = CaddyManager(mock_registry)
    with patch.object(manager, "_run_command") as mock_run:
        manager.start_caddy()
        mock_run.assert_called_once_with(["start", "--config", str(CADDY_CONFIG_PATH)])


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_caddy_manager_stop(mock_get_path, mock_registry):
    """Test stopping Caddy."""
    manager = CaddyManager(mock_registry)
    with patch.object(manager, "_run_command") as mock_run:
        manager.stop_caddy()
        mock_run.assert_called_once_with(["stop"])


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_caddy_manager_reload(mock_get_path, mock_registry):
    """Test reloading Caddy."""
    manager = CaddyManager(mock_registry)
    with patch.object(manager, "_run_command") as mock_run, \
         patch.object(manager, "generate_caddyfile") as mock_generate:
        manager.reload_caddy()
        mock_generate.assert_called_once()
        mock_run.assert_called_once_with(["reload", "--config", str(CADDY_CONFIG_PATH)])
