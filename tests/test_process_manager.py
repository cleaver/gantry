"""Tests for the ProcessManager."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from gantry.port_allocator import PortAllocator, PortConflictError
from gantry.process_manager import (
    MIN_PORT,
    MAX_PORT,
    ProcessManager,
    ProcessManagerError,
    ServiceAlreadyRunningError,
    DockerComposeNotFoundError,
    _load_state,
    _save_state,
    _clear_state,
)
from gantry.registry import Registry


@pytest.fixture
def process_manager(mock_registry, port_allocator):
    """Fixture for a ProcessManager instance."""
    return ProcessManager(mock_registry, port_allocator)


@pytest.fixture
def registered_project(mock_registry: Registry, sample_project_path: Path):
    """Fixture to create and register a sample project."""
    compose_content = {
        "services": {
            "web": {"ports": ["8080:80"]},
            "db": {"ports": ["5433:5432"]},
        }
    }
    (sample_project_path / "docker-compose.yml").write_text(
        json.dumps(compose_content)
    )

    project = mock_registry.register_project(
        hostname="test-project",
        path=sample_project_path,
        port=5001,
    )
    mock_registry.update_project_metadata(
        "test-project",
        exposed_ports=[5001, 8080, 5433],
        service_ports={"web": 8080, "db": 5433},
        docker_compose=True,
        working_directory=sample_project_path,
    )
    return mock_registry.get_project("test-project")


# ============================================================================
# Subprocess Mocking Tests
# ============================================================================

class TestSubprocessMocking:
    """Test subprocess call mocking for various scenarios."""

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="stopped")
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.ProcessManager._get_docker_compose_pids")
    @patch("gantry.process_manager.time.sleep")
    def test_docker_compose_up_success(
        self,
        mock_sleep,
        mock_get_pids,
        mock_subprocess_run,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test successful docker compose up -d call."""
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout="OK", stderr=""
        )
        mock_get_pids.return_value = [123, 456]

        process_manager.start_project("test-project")

        # Check that subprocess.run was called with correct arguments
        assert mock_subprocess_run.called
        call_args = mock_subprocess_run.call_args
        assert call_args[0][0] == ["docker", "compose", "up", "-d"]
        assert call_args[1]["cwd"] == registered_project.working_directory
        assert "env" in call_args[1]
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["text"] is True
        assert call_args[1]["check"] is True
        assert call_args[1]["timeout"] == 120
        mock_get_pids.assert_called_once()
        updated_project = mock_registry.get_project("test-project")
        assert updated_project.status == "running"

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="stopped")
    @patch("gantry.process_manager.subprocess.run")
    def test_docker_compose_up_failure(
        self,
        mock_subprocess_run,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test docker compose up failure raises ProcessManagerError."""
        mock_subprocess_run.side_effect = subprocess.CalledProcessError(
            1, "docker compose", stderr="Error starting services"
        )

        with pytest.raises(ProcessManagerError, match="Failed to start"):
            process_manager.start_project("test-project")

        updated_project = mock_registry.get_project("test-project")
        assert updated_project.status == "error"

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="stopped")
    @patch("gantry.process_manager.subprocess.run")
    def test_docker_compose_up_timeout(
        self,
        mock_subprocess_run,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test docker compose up timeout raises ProcessManagerError."""
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired("docker compose", 120)

        with pytest.raises(ProcessManagerError, match="Timeout starting"):
            process_manager.start_project("test-project")

        updated_project = mock_registry.get_project("test-project")
        assert updated_project.status == "error"

    @patch("gantry.process_manager.subprocess.run")
    def test_docker_compose_ps_for_status(
        self,
        mock_subprocess_run,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test docker compose ps call for status checking."""
        # Mock running services
        mock_subprocess_run.return_value = MagicMock(
            returncode=0,
            stdout='{"State": "running", "Name": "web"}\n{"State": "up", "Name": "db"}',
        )

        status = process_manager.get_status("test-project")

        assert status == "running"
        # Check that subprocess.run was called with correct arguments
        assert mock_subprocess_run.called
        call_args = mock_subprocess_run.call_args
        assert call_args[0][0] == ["docker", "compose", "ps", "--format", "json"]
        assert call_args[1]["cwd"] == registered_project.working_directory
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["text"] is True
        assert call_args[1]["timeout"] == 10

    @patch("gantry.process_manager.subprocess.run")
    def test_docker_compose_ps_failure_returns_error(
        self,
        mock_subprocess_run,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test docker compose ps failure returns error status."""
        mock_subprocess_run.return_value = MagicMock(returncode=1)

        status = process_manager.get_status("test-project")

        assert status == "error"
        updated_project = mock_registry.get_project("test-project")
        assert updated_project.status == "error"

    @patch("gantry.process_manager.subprocess.run")
    def test_docker_compose_ps_timeout_returns_error(
        self,
        mock_subprocess_run,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test docker compose ps timeout returns error status."""
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired("docker compose", 10)

        status = process_manager.get_status("test-project")

        assert status == "error"
        updated_project = mock_registry.get_project("test-project")
        assert updated_project.status == "error"

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="running")
    @patch("gantry.process_manager._load_state", return_value={"pids": [123]})
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.psutil.pid_exists", return_value=True)
    @patch("gantry.process_manager.psutil.Process")
    @patch("gantry.process_manager._clear_state")
    @patch("gantry.process_manager.time.sleep")
    def test_docker_compose_down_success(
        self,
        mock_sleep,
        mock_clear_state,
        mock_process,
        mock_pid_exists,
        mock_subprocess_run,
        mock_load_state,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test successful docker compose down call."""
        mock_registry.update_project_status("test-project", "running")
        mock_subprocess_run.return_value = MagicMock(returncode=0)

        process_manager.stop_project("test-project")

        # Check that subprocess.run was called with correct arguments
        assert mock_subprocess_run.called
        call_args = mock_subprocess_run.call_args
        assert call_args[0][0] == ["docker", "compose", "down"]
        assert call_args[1]["cwd"] == registered_project.working_directory
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["text"] is True
        assert call_args[1]["timeout"] == process_manager._shutdown_timeout
        mock_clear_state.assert_called_once_with("test-project")
        assert mock_registry.get_project("test-project").status == "stopped"

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="running")
    @patch("gantry.process_manager._load_state", return_value={"pids": [123]})
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.psutil.pid_exists", return_value=True)
    @patch("gantry.process_manager.psutil.Process")
    @patch("gantry.process_manager._clear_state")
    @patch("gantry.process_manager.time.sleep")
    def test_docker_compose_down_timeout_force_kills(
        self,
        mock_sleep,
        mock_clear_state,
        mock_process_class,
        mock_pid_exists,
        mock_subprocess_run,
        mock_load_state,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test docker compose down timeout triggers force kill."""
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired("docker compose", 30)
        mock_process = MagicMock()
        mock_process_class.return_value = mock_process

        process_manager.stop_project("test-project")

        # Should attempt to kill PIDs
        assert mock_process_class.called or mock_pid_exists.called
        mock_clear_state.assert_called_once()

    @patch("gantry.process_manager.subprocess.Popen")
    def test_docker_compose_logs_call(
        self,
        mock_popen,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test docker compose logs subprocess call."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process

        result = process_manager.get_logs("test-project", follow=True)

        # Check that subprocess.Popen was called with correct arguments
        assert mock_popen.called
        call_args = mock_popen.call_args
        assert call_args[0][0] == ["docker", "compose", "logs", "--follow"]
        assert call_args[1]["cwd"] == registered_project.working_directory
        assert call_args[1]["stdout"] == subprocess.PIPE
        assert call_args[1]["stderr"] == subprocess.STDOUT
        assert call_args[1]["text"] is True
        assert call_args[1]["bufsize"] == 1
        assert result == mock_process

    @patch("gantry.process_manager.subprocess.Popen")
    def test_docker_compose_logs_with_service(
        self,
        mock_popen,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test docker compose logs with specific service."""
        mock_process = MagicMock()
        mock_popen.return_value = mock_process

        result = process_manager.get_logs("test-project", service="web", follow=False)

        # Check that subprocess.Popen was called with correct arguments
        assert mock_popen.called
        call_args = mock_popen.call_args
        assert call_args[0][0] == ["docker", "compose", "logs", "web"]
        assert call_args[1]["cwd"] == registered_project.working_directory
        assert call_args[1]["stdout"] == subprocess.PIPE
        assert call_args[1]["stderr"] == subprocess.STDOUT
        assert call_args[1]["text"] is True
        assert call_args[1]["bufsize"] == 1

    @patch("gantry.process_manager.subprocess.run")
    def test_get_docker_compose_pids_success(
        self,
        mock_subprocess_run,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test _get_docker_compose_pids with valid output."""
        mock_subprocess_run.return_value = MagicMock(
            returncode=0,
            stdout='{"Pid": "123"}\n{"Pid": "456"}\n{"Pid": ""}',
        )

        pids = process_manager._get_docker_compose_pids(registered_project.path)

        assert pids == [123, 456]

    @patch("gantry.process_manager.subprocess.run")
    def test_get_docker_compose_pids_handles_errors(
        self,
        mock_subprocess_run,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test _get_docker_compose_pids handles subprocess errors."""
        mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, "docker")

        pids = process_manager._get_docker_compose_pids(registered_project.path)

        assert pids == []


# ============================================================================
# Start/Stop Lifecycle Tests
# ============================================================================

class TestStartProject:
    """Tests for the start_project method."""

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="stopped")
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.ProcessManager._get_docker_compose_pids")
    @patch("gantry.process_manager.time.sleep")
    def test_start_project_success(
        self,
        mock_sleep,
        mock_get_pids,
        mock_subprocess_run,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test successful project startup."""
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout="OK", stderr=""
        )
        mock_get_pids.return_value = [123, 456]

        process_manager.start_project("test-project")

        mock_get_status.assert_called_once_with("test-project")
        # Check that subprocess.run was called with correct arguments
        assert mock_subprocess_run.called
        call_args = mock_subprocess_run.call_args
        assert call_args[0][0] == ["docker", "compose", "up", "-d"]
        assert call_args[1]["cwd"] == registered_project.working_directory
        assert "env" in call_args[1]
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["text"] is True
        assert call_args[1]["check"] is True
        assert call_args[1]["timeout"] == 120

        updated_project = mock_registry.get_project("test-project")
        assert updated_project.status == "running"
        assert updated_project.last_started is not None

    @patch("gantry.process_manager.subprocess.run")
    def test_start_project_already_running(
        self, mock_subprocess_run, process_manager: ProcessManager, registered_project
    ):
        """Test starting an already running project raises an error."""
        with patch.object(
            process_manager, "get_status", return_value="running"
        ) as mock_get_status:
            with pytest.raises(ServiceAlreadyRunningError):
                process_manager.start_project("test-project")
            mock_get_status.assert_called_once_with("test-project")

    def test_start_project_port_conflict_no_force(
        self, process_manager: ProcessManager, registered_project
    ):
        """Test port conflict without force flag raises PortConflictError."""
        conflicts = [{"port": 5001, "conflicting_project": "other"}]
        with patch.object(
            process_manager, "check_startup_conflicts", return_value=conflicts
        ):
            with pytest.raises(PortConflictError):
                process_manager.start_project("test-project")

    @patch("gantry.process_manager.logging.warning")
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.ProcessManager.get_status", return_value="stopped")
    @patch("gantry.process_manager.ProcessManager._get_docker_compose_pids")
    @patch("gantry.process_manager.time.sleep")
    def test_start_project_port_conflict_with_force(
        self,
        mock_sleep,
        mock_get_pids,
        mock_get_status,
        mock_subprocess_run,
        mock_log_warning,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test port conflict with force flag logs a warning and proceeds."""
        conflicts = [{"port": 5001, "conflicting_project": "other"}]
        mock_subprocess_run.return_value = MagicMock(returncode=0)
        mock_get_pids.return_value = []
        with patch.object(
            process_manager, "check_startup_conflicts", return_value=conflicts
        ):
            process_manager.start_project("test-project", force=True)

        mock_log_warning.assert_called_once()
        mock_subprocess_run.assert_called()

    @patch("gantry.process_manager.subprocess.run")
    def test_start_project_invalid_port(
        self, mock_subprocess_run, process_manager: ProcessManager, registered_project
    ):
        """Test starting with a port outside the allowed range."""
        with pytest.raises(ValueError, match="outside the allowed range"):
            process_manager.start_project("test-project", port=9999)

        mock_subprocess_run.assert_not_called()

    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.ProcessManager.get_status", return_value="stopped")
    @patch("gantry.process_manager.ProcessManager._get_docker_compose_pids")
    @patch("gantry.process_manager.time.sleep")
    def test_start_project_with_valid_port_update(
        self,
        mock_sleep,
        mock_get_pids,
        mock_get_status,
        mock_subprocess_run,
        process_manager: ProcessManager,
        mock_registry: Registry,
        registered_project,
    ):
        """Test starting with a valid new port updates the registry."""
        new_port = 5050
        assert registered_project.port != new_port
        mock_subprocess_run.return_value = MagicMock(returncode=0)
        mock_get_pids.return_value = []

        process_manager.start_project("test-project", port=new_port)

        updated_project = mock_registry.get_project("test-project")
        assert updated_project.port == new_port
        mock_subprocess_run.assert_called()

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="stopped")
    def test_start_project_no_compose_file(
        self,
        mock_get_status,
        process_manager: ProcessManager,
        mock_registry: Registry,
        tmp_path,
    ):
        """Test starting project without docker-compose.yml raises error."""
        project_path = tmp_path / "no-compose"
        project_path.mkdir()
        mock_registry.register_project(
            hostname="no-compose",
            path=project_path,
            port=5001,
        )

        with pytest.raises(DockerComposeNotFoundError):
            process_manager.start_project("no-compose")

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="stopped")
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.ProcessManager._get_docker_compose_pids")
    @patch("gantry.process_manager.time.sleep")
    def test_start_project_saves_state(
        self,
        mock_sleep,
        mock_get_pids,
        mock_subprocess_run,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
        tmp_gantry_home,
    ):
        """Test that start_project saves state with PIDs."""
        mock_subprocess_run.return_value = MagicMock(returncode=0)
        mock_get_pids.return_value = [123, 456]

        process_manager.start_project("test-project")

        state = _load_state("test-project")
        assert "pids" in state
        assert state["pids"] == [123, 456]
        assert "started_at" in state


class TestStopProject:
    """Tests for the stop_project method."""

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="running")
    @patch("gantry.process_manager._load_state", return_value={"pids": [123]})
    @patch("gantry.process_manager.psutil.pid_exists", return_value=True)
    @patch("gantry.process_manager.psutil.Process")
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager._clear_state")
    @patch("gantry.process_manager.time.sleep")
    def test_stop_project_success(
        self,
        mock_sleep,
        mock_clear_state,
        mock_subprocess_run,
        mock_process,
        mock_pid_exists,
        mock_load_state,
        mock_get_status,
        process_manager: ProcessManager,
        mock_registry: Registry,
        registered_project,
    ):
        """Test successful project shutdown."""
        mock_registry.update_project_status("test-project", "running")
        mock_subprocess_run.return_value = MagicMock(returncode=0)

        process_manager.stop_project("test-project")

        # Check that subprocess.run was called with correct arguments
        assert mock_subprocess_run.called
        call_args = mock_subprocess_run.call_args
        assert call_args[0][0] == ["docker", "compose", "down"]
        assert call_args[1]["cwd"] == registered_project.working_directory
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["text"] is True
        assert call_args[1]["timeout"] == process_manager._shutdown_timeout
        mock_clear_state.assert_called_once_with("test-project")
        assert mock_registry.get_project("test-project").status == "stopped"

    def test_stop_project_already_stopped(
        self, process_manager: ProcessManager, mock_registry: Registry, registered_project
    ):
        """Test stopping an already stopped project does nothing."""
        mock_registry.update_project_status("test-project", "stopped")

        with patch.object(
            process_manager, "get_status", return_value="stopped"
        ) as mock_get_status:
            process_manager.stop_project("test-project")
            mock_get_status.assert_called_once()

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="running")
    @patch("gantry.process_manager._load_state", return_value={"pids": [123, 456]})
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.psutil.pid_exists")
    @patch("gantry.process_manager.psutil.Process")
    @patch("gantry.process_manager._clear_state")
    @patch("gantry.process_manager.time.sleep")
    def test_stop_project_force_kills_remaining_pids(
        self,
        mock_sleep,
        mock_clear_state,
        mock_process_class,
        mock_pid_exists,
        mock_subprocess_run,
        mock_load_state,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test that stop_project force kills remaining PIDs after graceful shutdown."""
        mock_subprocess_run.return_value = MagicMock(returncode=0)
        # First call returns True (PID still exists), second call returns False (killed)
        mock_pid_exists.side_effect = [True, True, False, False]
        mock_process = MagicMock()
        mock_process_class.return_value = mock_process

        process_manager.stop_project("test-project")

        # Should call terminate and kill on processes
        assert mock_process_class.called
        mock_clear_state.assert_called_once()

    @patch("gantry.process_manager.ProcessManager.get_status", return_value="running")
    @patch("gantry.process_manager._load_state", return_value={"pids": [123]})
    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager.psutil.pid_exists", return_value=True)
    @patch("gantry.process_manager.psutil.Process")
    @patch("gantry.process_manager._clear_state")
    @patch("gantry.process_manager.time.sleep")
    def test_stop_project_handles_psutil_errors(
        self,
        mock_sleep,
        mock_clear_state,
        mock_process_class,
        mock_pid_exists,
        mock_subprocess_run,
        mock_load_state,
        mock_get_status,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test that stop_project handles psutil errors gracefully."""
        import psutil
        mock_subprocess_run.return_value = MagicMock(returncode=0)
        mock_pid_exists.return_value = True
        # Raise exception when creating Process (which is what the code catches)
        mock_process_class.side_effect = psutil.AccessDenied(123, "Access denied")

        # Should not raise exception
        process_manager.stop_project("test-project")
        mock_clear_state.assert_called_once()


class TestRestartProject:
    """Tests for the restart_project method."""

    @patch("gantry.process_manager.ProcessManager.stop_project")
    @patch("gantry.process_manager.ProcessManager.start_project")
    @patch("gantry.process_manager.time.sleep")
    def test_restart_project_calls_stop_then_start(
        self,
        mock_sleep,
        mock_start,
        mock_stop,
        process_manager: ProcessManager,
    ):
        """Test that restart_project calls stop then start."""
        process_manager.restart_project("test-project")

        mock_stop.assert_called_once_with("test-project")
        mock_start.assert_called_once_with("test-project")
        mock_sleep.assert_called_once()


class TestGetStatus:
    """Tests for the get_status method."""

    @patch("gantry.process_manager.subprocess.run")
    def test_get_status_running_from_compose(
        self,
        mock_subprocess_run,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test get_status returns running when Docker Compose shows running."""
        mock_subprocess_run.return_value = MagicMock(
            returncode=0,
            stdout='{"State": "running", "Name": "web"}',
        )

        status = process_manager.get_status("test-project")

        assert status == "running"
        updated_project = mock_registry.get_project("test-project")
        assert updated_project.status == "running"

    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager._load_state", return_value={"pids": [123]})
    @patch("gantry.process_manager.psutil.pid_exists", return_value=True)
    @patch("gantry.process_manager.psutil.Process")
    def test_get_status_running_from_pids(
        self,
        mock_process_class,
        mock_pid_exists,
        mock_load_state,
        mock_subprocess_run,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test get_status returns running when PIDs are valid."""
        mock_subprocess_run.return_value = MagicMock(
            returncode=0,
            stdout='{"State": "stopped", "Name": "web"}',
        )
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process_class.return_value = mock_process

        status = process_manager.get_status("test-project")

        assert status == "running"

    @patch("gantry.process_manager.subprocess.run")
    @patch("gantry.process_manager._load_state", return_value={})
    def test_get_status_stopped(
        self,
        mock_load_state,
        mock_subprocess_run,
        process_manager: ProcessManager,
        registered_project,
        mock_registry: Registry,
    ):
        """Test get_status returns stopped when no services running."""
        mock_subprocess_run.return_value = MagicMock(
            returncode=0,
            stdout='{"State": "stopped", "Name": "web"}',
        )

        status = process_manager.get_status("test-project")

        assert status == "stopped"
        updated_project = mock_registry.get_project("test-project")
        assert updated_project.status == "stopped"

    def test_get_status_no_compose_file(
        self,
        process_manager: ProcessManager,
        mock_registry: Registry,
        tmp_path,
    ):
        """Test get_status returns registry status when no compose file."""
        project_path = tmp_path / "no-compose"
        project_path.mkdir()
        mock_registry.register_project(
            hostname="no-compose",
            path=project_path,
            port=5001,
        )
        mock_registry.update_project_status("no-compose", "running")

        status = process_manager.get_status("no-compose")

        assert status == "running"

    def test_get_status_nonexistent_project(
        self,
        process_manager: ProcessManager,
    ):
        """Test get_status raises ValueError for nonexistent project."""
        with pytest.raises(ValueError, match="not found"):
            process_manager.get_status("nonexistent")


class TestPidValidation:
    """Tests for PID validation and state persistence."""

    @patch("gantry.process_manager.psutil.pid_exists", return_value=True)
    @patch("gantry.process_manager.psutil.Process")
    def test_validate_pids_returns_running_pids(
        self,
        mock_process_class,
        mock_pid_exists,
        process_manager: ProcessManager,
    ):
        """Test _validate_pids returns only running PIDs."""
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process_class.return_value = mock_process

        valid_pids = process_manager._validate_pids([123, 456])

        assert valid_pids == [123, 456]

    @patch("gantry.process_manager.psutil.pid_exists")
    @patch("gantry.process_manager.psutil.Process")
    def test_validate_pids_filters_dead_pids(
        self,
        mock_process_class,
        mock_pid_exists,
        process_manager: ProcessManager,
    ):
        """Test _validate_pids filters out dead PIDs."""
        mock_pid_exists.side_effect = [True, False]  # First exists, second doesn't
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process_class.return_value = mock_process

        valid_pids = process_manager._validate_pids([123, 456])

        assert valid_pids == [123]

    @patch("gantry.process_manager.psutil.pid_exists", return_value=True)
    @patch("gantry.process_manager.psutil.Process")
    def test_validate_pids_handles_exceptions(
        self,
        mock_process_class,
        mock_pid_exists,
        process_manager: ProcessManager,
    ):
        """Test _validate_pids handles psutil exceptions gracefully."""
        import psutil
        mock_process_class.side_effect = psutil.AccessDenied(123, "Access denied")

        valid_pids = process_manager._validate_pids([123])

        assert valid_pids == []


# ============================================================================
# Health Check Logic Tests
# ============================================================================

class TestHealthCheck:
    """Tests for the health_check method."""

    @patch("gantry.process_manager.urlopen")
    def test_health_check_success_200(
        self, mock_urlopen, process_manager: ProcessManager, registered_project
    ):
        """Test a successful health check with 200 status code."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = process_manager.health_check("test-project")

        assert result is True
        mock_urlopen.assert_called_once_with(
            f"http://localhost:{registered_project.port}", timeout=5
        )

    @patch("gantry.process_manager.urlopen")
    def test_health_check_success_299(
        self, mock_urlopen, process_manager: ProcessManager, registered_project
    ):
        """Test a successful health check with 299 status code."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 299
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = process_manager.health_check("test-project")

        assert result is True

    @patch("gantry.process_manager.urlopen")
    def test_health_check_failure_400(
        self, mock_urlopen, process_manager: ProcessManager, registered_project
    ):
        """Test health check fails with 400 status code."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 400
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = process_manager.health_check("test-project")

        assert result is False

    @patch("gantry.process_manager.urlopen")
    def test_health_check_failure_500(
        self, mock_urlopen, process_manager: ProcessManager, registered_project
    ):
        """Test health check fails with 500 status code."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 500
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = process_manager.health_check("test-project")

        assert result is False

    @patch("gantry.process_manager.urlopen")
    @patch("gantry.process_manager.time.sleep")
    def test_health_check_retry_logic(
        self,
        mock_sleep,
        mock_urlopen,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test that health check retries on connection errors."""
        # First two attempts fail with exception, third succeeds
        from urllib.error import URLError
        mock_response_success = MagicMock()
        mock_response_success.getcode.return_value = 200
        mock_urlopen.side_effect = [
            URLError("Connection failed"),
            URLError("Connection failed"),
            MagicMock(__enter__=MagicMock(return_value=mock_response_success)),
        ]

        result = process_manager.health_check("test-project")

        assert result is True
        assert mock_urlopen.call_count == 3
        assert mock_sleep.call_count == 2  # Sleeps between retries

    @patch("gantry.process_manager.urlopen")
    @patch("gantry.process_manager.time.sleep")
    def test_health_check_failure_after_retries(
        self,
        mock_sleep,
        mock_urlopen,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test that health check fails after all retries exhausted."""
        mock_urlopen.side_effect = URLError("Connection failed")

        result = process_manager.health_check("test-project")

        assert result is False
        assert mock_urlopen.call_count == 3  # 1 initial + 2 retries
        assert mock_sleep.call_count == 2

    @patch("gantry.process_manager.urlopen")
    @patch("gantry.process_manager.time.sleep")
    def test_health_check_connection_error(
        self,
        mock_sleep,
        mock_urlopen,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test health check handles connection errors."""
        mock_urlopen.side_effect = OSError("Connection refused")

        result = process_manager.health_check("test-project")

        assert result is False
        assert mock_urlopen.call_count == 3

    def test_health_check_no_port_configured(
        self,
        process_manager: ProcessManager,
        mock_registry: Registry,
        tmp_path,
    ):
        """Test health check returns False when no port configured."""
        project_path = tmp_path / "no-port"
        project_path.mkdir()
        mock_registry.register_project(
            hostname="no-port",
            path=project_path,
            port=None,
        )

        result = process_manager.health_check("no-port")

        assert result is False

    @patch("gantry.process_manager.urlopen")
    @patch("gantry.process_manager._load_state", return_value={})
    @patch("gantry.process_manager._save_state")
    def test_health_check_saves_timestamp(
        self,
        mock_save_state,
        mock_load_state,
        mock_urlopen,
        process_manager: ProcessManager,
        registered_project,
    ):
        """Test that successful health check saves timestamp to state."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        process_manager.health_check("test-project")

        mock_save_state.assert_called_once()
        call_args = mock_save_state.call_args
        assert "test-project" in call_args[0]
        state = call_args[0][1]
        assert "last_health_check" in state

    def test_health_check_nonexistent_project(
        self,
        process_manager: ProcessManager,
    ):
        """Test health check raises ValueError for nonexistent project."""
        with pytest.raises(ValueError, match="not found"):
            process_manager.health_check("nonexistent")
