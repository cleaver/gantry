"""Tests for the Orchestrator."""

from unittest.mock import MagicMock, patch

import pytest

from gantry.orchestrator import Orchestrator
from gantry.process_manager import ProcessManager
from gantry.registry import Project, Registry


@pytest.fixture
def mock_process_manager():
    """Create a mock ProcessManager."""
    return MagicMock(spec=ProcessManager)


@pytest.fixture
def orchestrator(mock_registry, mock_process_manager):
    """Create an Orchestrator instance with mocked dependencies."""
    return Orchestrator(mock_registry, mock_process_manager)


@pytest.fixture
def running_project(mock_registry, tmp_path):
    """Create a running project in the registry."""
    project_path = tmp_path / "running-project"
    project_path.mkdir()
    project = mock_registry.register_project(
        hostname="running-project",
        path=project_path,
        port=5001,
    )
    mock_registry.update_project_status("running-project", "running")
    return project


@pytest.fixture
def stopped_project(mock_registry, tmp_path):
    """Create a stopped project in the registry."""
    project_path = tmp_path / "stopped-project"
    project_path.mkdir()
    project = mock_registry.register_project(
        hostname="stopped-project",
        path=project_path,
        port=5002,
    )
    mock_registry.update_project_status("stopped-project", "stopped")
    return project


# ============================================================================
# Lifecycle Tests
# ============================================================================


class TestStopAll:
    """Tests for the stop_all method."""

    def test_stop_all_with_multiple_running_projects(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test stop_all stops multiple running projects."""
        # Create multiple running projects
        for i in range(3):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5001 + i,
            )
            mock_registry.update_project_status(f"project{i}", "running")

        stopped = orchestrator.stop_all()

        assert len(stopped) == 3
        assert set(stopped) == {"project0", "project1", "project2"}
        assert mock_process_manager.stop_project.call_count == 3

    def test_stop_all_handles_failures_gracefully(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test stop_all continues stopping other projects when one fails."""
        # Create multiple running projects
        for i in range(3):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5001 + i,
            )
            mock_registry.update_project_status(f"project{i}", "running")

        # Make stop_project fail for project1
        def side_effect(hostname):
            if hostname == "project1":
                raise Exception("Failed to stop")
            return None

        mock_process_manager.stop_project.side_effect = side_effect

        stopped = orchestrator.stop_all()

        # Should stop project0 and project2, but not project1
        assert len(stopped) == 2
        assert "project0" in stopped
        assert "project2" in stopped
        assert "project1" not in stopped
        assert mock_process_manager.stop_project.call_count == 3

    def test_stop_all_with_no_running_projects(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test stop_all returns empty list when no projects are running."""
        # Create stopped projects
        for i in range(2):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5001 + i,
            )
            mock_registry.update_project_status(f"project{i}", "stopped")

        stopped = orchestrator.stop_all()

        assert stopped == []
        mock_process_manager.stop_project.assert_not_called()

    def test_stop_all_with_empty_registry(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
    ):
        """Test stop_all with empty registry."""
        stopped = orchestrator.stop_all()

        assert stopped == []
        mock_process_manager.stop_project.assert_not_called()

    @patch("gantry.orchestrator.logging.error")
    def test_stop_all_logs_errors(
        self,
        mock_log_error,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test that stop_all logs errors when stopping fails."""
        project_path = tmp_path / "failing-project"
        project_path.mkdir()
        mock_registry.register_project(
            hostname="failing-project",
            path=project_path,
            port=5001,
        )
        mock_registry.update_project_status("failing-project", "running")

        mock_process_manager.stop_project.side_effect = Exception("Stop failed")

        stopped = orchestrator.stop_all()

        assert stopped == []
        mock_log_error.assert_called_once()


class TestGetAllStatus:
    """Tests for the get_all_status method."""

    def test_get_all_status_aggregates_all_projects(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test get_all_status returns status for all projects."""
        # Create multiple projects with different statuses
        for i, status in enumerate(["running", "stopped", "error"]):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5001 + i,
            )
            mock_registry.update_project_status(f"project{i}", status)

        mock_process_manager.get_status.side_effect = ["running", "stopped", "error"]

        statuses = orchestrator.get_all_status()

        assert len(statuses) == 3
        assert statuses["project0"] == "running"
        assert statuses["project1"] == "stopped"
        assert statuses["project2"] == "error"
        assert mock_process_manager.get_status.call_count == 3

    def test_get_all_status_updates_registry(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test that get_all_status updates registry status as side effect."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        mock_registry.register_project(
            hostname="test-project",
            path=project_path,
            port=5001,
        )
        mock_registry.update_project_status("test-project", "stopped")

        # Mock get_status to return running (different from registry)
        mock_process_manager.get_status.return_value = "running"

        statuses = orchestrator.get_all_status()

        # get_status should update registry internally
        assert statuses["test-project"] == "running"

    def test_get_all_status_handles_errors(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test that get_all_status handles errors for individual projects."""
        # Create multiple projects
        for i in range(2):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5001 + i,
            )

        # Make get_status fail for project1
        def side_effect(hostname):
            if hostname == "project1":
                raise Exception("Status check failed")
            return "running"

        mock_process_manager.get_status.side_effect = side_effect

        statuses = orchestrator.get_all_status()

        assert statuses["project0"] == "running"
        assert statuses["project1"] == "error"

    def test_get_all_status_with_empty_registry(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
    ):
        """Test get_all_status with empty registry."""
        statuses = orchestrator.get_all_status()

        assert statuses == {}
        mock_process_manager.get_status.assert_not_called()

    @patch("gantry.orchestrator.logging.error")
    def test_get_all_status_logs_errors(
        self,
        mock_log_error,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test that get_all_status logs errors when status check fails."""
        project_path = tmp_path / "test-project"
        project_path.mkdir()
        mock_registry.register_project(
            hostname="test-project",
            path=project_path,
            port=5001,
        )

        mock_process_manager.get_status.side_effect = Exception("Status failed")

        statuses = orchestrator.get_all_status()

        assert statuses["test-project"] == "error"
        mock_log_error.assert_called_once()


# ============================================================================
# Health Check Logic Tests
# ============================================================================


class TestWatchServices:
    """Tests for the watch_services method."""

    def test_watch_services_single_run_mode(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        running_project: Project,
    ):
        """Test watch_services in single_run mode performs one check."""
        mock_process_manager.get_status.return_value = "running"
        mock_process_manager.health_check.return_value = True

        orchestrator.watch_services(interval=60, single_run=True)

        # Should check status and health for running project
        assert mock_process_manager.get_status.called
        assert mock_process_manager.health_check.called

    def test_watch_services_calls_health_check_for_running_projects(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        running_project: Project,
        stopped_project: Project,
    ):
        """Test watch_services calls health_check only for running projects."""
        mock_process_manager.get_status.side_effect = ["running", "stopped"]
        mock_process_manager.health_check.return_value = True

        orchestrator.watch_services(interval=60, single_run=True)

        # Should only call health_check for running project
        mock_process_manager.health_check.assert_called_once_with("running-project")

    def test_watch_services_handles_health_check_failures(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        running_project: Project,
    ):
        """Test watch_services handles health check failures."""
        mock_process_manager.get_status.return_value = "running"
        mock_process_manager.health_check.return_value = False

        orchestrator.watch_services(interval=60, single_run=True)

        # Should call health_check and handle failure
        mock_process_manager.health_check.assert_called_once_with("running-project")

    @patch("gantry.orchestrator.logging.warning")
    def test_watch_services_logs_health_check_failures(
        self,
        mock_log_warning,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        running_project: Project,
    ):
        """Test that watch_services logs warnings for failed health checks."""
        mock_process_manager.get_status.return_value = "running"
        mock_process_manager.health_check.return_value = False

        orchestrator.watch_services(interval=60, single_run=True)

        mock_log_warning.assert_called_once()
        assert "failed health check" in mock_log_warning.call_args[0][0].lower()

    def test_watch_services_handles_get_status_errors(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        running_project: Project,
    ):
        """Test watch_services handles errors in get_status."""
        mock_process_manager.get_status.side_effect = Exception("Status check failed")

        # Should not raise exception
        orchestrator.watch_services(interval=60, single_run=True)

        # Should have attempted to get status
        assert mock_process_manager.get_status.called

    @patch("gantry.orchestrator.logging.error")
    def test_watch_services_logs_get_status_errors(
        self,
        mock_log_error,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        running_project: Project,
    ):
        """Test that watch_services logs errors from get_status."""
        mock_process_manager.get_status.side_effect = Exception("Status check failed")

        orchestrator.watch_services(interval=60, single_run=True)

        mock_log_error.assert_called_once()

    def test_watch_services_handles_health_check_errors(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        running_project: Project,
    ):
        """Test watch_services handles errors in health_check."""
        mock_process_manager.get_status.return_value = "running"
        mock_process_manager.health_check.side_effect = Exception("Health check failed")

        # Should not raise exception
        orchestrator.watch_services(interval=60, single_run=True)

        # Should have attempted health check
        assert mock_process_manager.health_check.called

    @patch("gantry.orchestrator.logging.error")
    def test_watch_services_logs_health_check_errors(
        self,
        mock_log_error,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        running_project: Project,
    ):
        """Test that watch_services logs errors from health_check."""
        mock_process_manager.get_status.return_value = "running"
        mock_process_manager.health_check.side_effect = Exception("Health check failed")

        orchestrator.watch_services(interval=60, single_run=True)

        mock_log_error.assert_called_once()

    def test_watch_services_with_no_running_projects(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        stopped_project: Project,
    ):
        """Test watch_services with no running projects."""
        mock_process_manager.get_status.return_value = "stopped"

        orchestrator.watch_services(interval=60, single_run=True)

        # Should not call health_check for stopped projects
        mock_process_manager.health_check.assert_not_called()

    @patch("gantry.orchestrator.logging.error")
    @patch.object(Registry, "get_running_projects")
    def test_watch_services_handles_loop_errors(
        self,
        mock_get_running_projects,
        mock_log_error,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
    ):
        """Test that watch_services handles errors in the monitoring loop."""
        # Make get_running_projects raise an error
        mock_get_running_projects.side_effect = Exception("Registry error")

        orchestrator.watch_services(interval=60, single_run=True)

        mock_log_error.assert_called_once()
        assert "watch_services loop" in mock_log_error.call_args[0][0].lower()

    def test_watch_services_multiple_running_projects(
        self,
        orchestrator: Orchestrator,
        mock_registry: Registry,
        mock_process_manager: MagicMock,
        tmp_path,
    ):
        """Test watch_services with multiple running projects."""
        # Create multiple running projects
        for i in range(3):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5001 + i,
            )
            mock_registry.update_project_status(f"project{i}", "running")

        mock_process_manager.get_status.return_value = "running"
        mock_process_manager.health_check.return_value = True

        orchestrator.watch_services(interval=60, single_run=True)

        # Should call health_check for each running project
        assert mock_process_manager.health_check.call_count == 3
