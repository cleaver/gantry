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


# --- Enhanced Subprocess Mocking Tests ---

@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
@patch("subprocess.run")
def test_caddy_manager_start_subprocess(mock_run, mock_get_path, mock_registry):
    """Test starting Caddy with subprocess mocking."""
    manager = CaddyManager(mock_registry)
    
    # Mock successful subprocess call
    mock_result = MagicMock()
    mock_result.check_returncode = MagicMock()
    mock_run.return_value = mock_result
    
    manager.start_caddy()
    
    # Verify subprocess was called with correct arguments
    mock_run.assert_called_once_with(
        ["/fake/caddy", "start", "--config", str(CADDY_CONFIG_PATH)],
        capture_output=True,
        text=True,
        check=True,
        cwd=CADDY_CONFIG_DIR
    )


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
@patch("subprocess.run")
def test_caddy_manager_stop_subprocess(mock_run, mock_get_path, mock_registry):
    """Test stopping Caddy with subprocess mocking."""
    manager = CaddyManager(mock_registry)
    
    # Mock successful subprocess call
    mock_result = MagicMock()
    mock_result.check_returncode = MagicMock()
    mock_run.return_value = mock_result
    
    manager.stop_caddy()
    
    # Verify subprocess was called with correct arguments
    mock_run.assert_called_once_with(
        ["/fake/caddy", "stop"],
        capture_output=True,
        text=True,
        check=True,
        cwd=CADDY_CONFIG_DIR
    )


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
@patch("subprocess.run")
def test_caddy_manager_reload_subprocess(mock_run, mock_get_path, mock_registry):
    """Test reloading Caddy with subprocess mocking."""
    manager = CaddyManager(mock_registry)
    
    # Mock successful subprocess call
    mock_result = MagicMock()
    mock_result.check_returncode = MagicMock()
    mock_run.return_value = mock_result
    
    with patch.object(manager, "generate_caddyfile") as mock_generate:
        manager.reload_caddy()
        
        # Verify generate_caddyfile was called first
        mock_generate.assert_called_once()
        
        # Verify subprocess was called with correct arguments
        mock_run.assert_called_once_with(
            ["/fake/caddy", "reload", "--config", str(CADDY_CONFIG_PATH)],
            capture_output=True,
            text=True,
            check=True,
            cwd=CADDY_CONFIG_DIR
        )


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
@patch("subprocess.run")
def test_caddy_manager_run_command_file_not_found(mock_run, mock_get_path, mock_registry):
    """Test _run_command handles FileNotFoundError."""
    manager = CaddyManager(mock_registry)
    
    # Mock FileNotFoundError
    mock_run.side_effect = FileNotFoundError("caddy not found")
    
    with pytest.raises(CaddyMissingError, match="Caddy binary not found during command execution"):
        manager._run_command(["status"])


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
@patch("subprocess.run")
def test_caddy_manager_run_command_with_stderr(mock_run, mock_get_path, mock_registry):
    """Test _run_command error handling with stderr."""
    manager = CaddyManager(mock_registry)
    
    # Mock CalledProcessError with stderr
    error = subprocess.CalledProcessError(1, "cmd", stderr="Port 80 already in use")
    mock_run.side_effect = error
    
    with pytest.raises(CaddyCommandError, match="Caddy command failed: Port 80 already in use"):
        manager._run_command(["start", "--config", str(CADDY_CONFIG_PATH)])


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
@patch("subprocess.run")
def test_caddy_manager_run_command_with_stdout_error(mock_run, mock_get_path, mock_registry):
    """Test _run_command error handling when stderr is empty but stdout has error."""
    manager = CaddyManager(mock_registry)
    
    # Mock CalledProcessError with stdout but no stderr
    # CalledProcessError doesn't accept stdout/stderr in constructor, so set them as attributes
    error = subprocess.CalledProcessError(1, "cmd")
    error.stdout = "Error: configuration invalid"
    error.stderr = None
    mock_run.side_effect = error
    
    with pytest.raises(CaddyCommandError, match="Caddy command failed: Error: configuration invalid"):
        manager._run_command(["reload", "--config", str(CADDY_CONFIG_PATH)])


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
@patch("subprocess.run")
def test_caddy_manager_run_command_working_directory(mock_run, mock_get_path, mock_registry):
    """Test that _run_command uses correct working directory."""
    manager = CaddyManager(mock_registry)
    
    mock_result = MagicMock()
    mock_result.check_returncode = MagicMock()
    mock_run.return_value = mock_result
    
    manager._run_command(["status"])
    
    # Verify cwd parameter
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["cwd"] == CADDY_CONFIG_DIR


# --- Enhanced Caddyfile Generation Tests ---

@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_generate_caddyfile_empty_registry(mock_get_path):
    """Test Caddyfile generation with empty registry."""
    registry = MagicMock(spec=Registry)
    registry.list_projects.return_value = []
    manager = CaddyManager(registry)
    
    m = mock_open()
    with patch("pathlib.Path.write_text", m):
        caddyfile = manager.generate_caddyfile()
        
        # Should still have header and port configuration
        assert "# Auto-generated by Gantry" in caddyfile
        assert "http_port 80" in caddyfile
        assert "https_port 443" in caddyfile
        # But no project routes
        assert ".test" not in caddyfile


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_generate_caddyfile_no_services(mock_get_path):
    """Test Caddyfile generation for project with no services."""
    registry = MagicMock(spec=Registry)
    project = Project(
        hostname="simple",
        path=Path("/tmp/simple"),
        port=5001,
        service_ports={},
        exposed_ports=[5001],
        services=[],
        docker_compose=False,
        status="stopped",
        working_directory=Path("/tmp/simple"),
        environment_vars={},
        registered_at="2023-01-01T12:00:00Z",
        last_started=None,
        last_updated="2023-01-01T12:00:00Z"
    )
    registry.list_projects.return_value = [project]
    manager = CaddyManager(registry)
    
    m = mock_open()
    with patch("pathlib.Path.write_text", m):
        caddyfile = manager.generate_caddyfile()
        
        # Should have main route only
        assert "simple.test {" in caddyfile
        assert "reverse_proxy localhost:5001" in caddyfile
        # Should not have any service subdomains (check for pattern service.hostname.test)
        # Count occurrences of ".simple.test" - should only be 0 (main route is "simple.test", not ".simple.test")
        lines = caddyfile.split('\n')
        service_subdomain_lines = [line for line in lines if '.simple.test' in line]
        assert len(service_subdomain_lines) == 0


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_generate_caddyfile_multiple_services(mock_get_path):
    """Test Caddyfile generation with project having multiple services."""
    registry = MagicMock(spec=Registry)
    project = Project(
        hostname="multi",
        path=Path("/tmp/multi"),
        port=5001,
        service_ports={"db": 5432, "redis": 6379, "mail": 1025, "adminer": 8080},
        exposed_ports=[5001, 5432, 6379, 1025, 8080],
        services=["web", "db", "redis", "mail", "adminer"],
        docker_compose=True,
        status="stopped",
        working_directory=Path("/tmp/multi"),
        environment_vars={},
        registered_at="2023-01-01T12:00:00Z",
        last_started=None,
        last_updated="2023-01-01T12:00:00Z"
    )
    registry.list_projects.return_value = [project]
    manager = CaddyManager(registry)
    
    m = mock_open()
    with patch("pathlib.Path.write_text", m):
        caddyfile = manager.generate_caddyfile()
        
        # Check main route
        assert "multi.test" in caddyfile
        assert "reverse_proxy localhost:5001" in caddyfile
        
        # Check all service routes
        assert "db.multi.test" in caddyfile
        assert "reverse_proxy localhost:5432" in caddyfile
        assert "redis.multi.test" in caddyfile
        assert "reverse_proxy localhost:6379" in caddyfile
        assert "mail.multi.test" in caddyfile
        assert "reverse_proxy localhost:1025" in caddyfile
        assert "adminer.multi.test" in caddyfile
        assert "reverse_proxy localhost:8080" in caddyfile


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_generate_caddyfile_no_port(mock_get_path):
    """Test Caddyfile generation for project with no port."""
    registry = MagicMock(spec=Registry)
    project = Project(
        hostname="noport",
        path=Path("/tmp/noport"),
        port=None,
        service_ports={"db": 5432},
        exposed_ports=[5432],
        services=["db"],
        docker_compose=True,
        status="stopped",
        working_directory=Path("/tmp/noport"),
        environment_vars={},
        registered_at="2023-01-01T12:00:00Z",
        last_started=None,
        last_updated="2023-01-01T12:00:00Z"
    )
    registry.list_projects.return_value = [project]
    manager = CaddyManager(registry)
    
    m = mock_open()
    with patch("pathlib.Path.write_text", m):
        caddyfile = manager.generate_caddyfile()
        
        # Should not have main route (no port) - check for exact pattern, not substring
        # The pattern "noport.test {" would match "db.noport.test {" so we need to be more specific
        lines = caddyfile.split('\n')
        main_route_lines = [line for line in lines if line.strip() == "noport.test {"]
        assert len(main_route_lines) == 0, "Main route should not be generated when port is None"
        # But should have service route
        assert "db.noport.test {" in caddyfile
        assert "reverse_proxy localhost:5432" in caddyfile


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_generate_caddyfile_file_writing(mock_get_path, mock_registry):
    """Test that Caddyfile is written to correct path."""
    manager = CaddyManager(mock_registry)
    
    m = mock_open()
    with patch("pathlib.Path.write_text", m):
        caddyfile = manager.generate_caddyfile()
        
        # Verify write_text was called with the caddyfile content
        m.assert_called_once_with(caddyfile)


@patch("gantry.caddy_manager.get_caddy_path", return_value=Path("/fake/caddy"))
def test_generate_caddyfile_format(mock_get_path, mock_registry):
    """Test Caddyfile format correctness."""
    manager = CaddyManager(mock_registry)
    
    with patch("pathlib.Path.write_text"):
        caddyfile = manager.generate_caddyfile()
        
        # Check header
        assert caddyfile.startswith("# Auto-generated by Gantry")
        
        # Check global options block
        assert "{" in caddyfile
        assert "http_port 80" in caddyfile
        assert "https_port 443" in caddyfile
        assert "}" in caddyfile
        
        # Check project comments
        assert "# Project: proj1" in caddyfile
        assert "# Project: proj2" in caddyfile
        
        # Check route blocks format
        assert "proj1.test {" in caddyfile
        assert "reverse_proxy localhost:5001" in caddyfile
        assert "}" in caddyfile
