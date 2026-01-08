"""Tests for registry CRUD operations and metadata management."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gantry.registry import Registry


class TestRegisterProject:
    """Test register_project() method."""
    
    def test_register_new_project(self, mock_registry, tmp_path):
        """Test registering a new project with valid data."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        project = mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        assert project.hostname == "myproject"
        assert project.path == project_path.resolve()
        assert project.port == 5001
        assert project.status == "stopped"
        assert project.registered_at is not None
        assert project.last_updated is not None
        assert isinstance(project.registered_at, datetime)
        assert isinstance(project.last_updated, datetime)
    
    def test_register_project_rejects_duplicate_hostname(self, mock_registry, tmp_path):
        """Test that registering a duplicate hostname raises ValueError."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        with pytest.raises(ValueError, match="already registered"):
            mock_registry.register_project(
                hostname="myproject",
                path=tmp_path / "other",
                port=5002
            )
    
    def test_register_project_validates_metadata_structure(self, mock_registry, tmp_path):
        """Test that registered project has correct metadata structure."""
        project_path = tmp_path / "testproj"
        project_path.mkdir()
        
        project = mock_registry.register_project(
            hostname="testproj",
            path=project_path,
            port=5001
        )
        
        # Check all required fields
        assert hasattr(project, "hostname")
        assert hasattr(project, "path")
        assert hasattr(project, "port")
        assert hasattr(project, "services")
        assert hasattr(project, "service_ports")
        assert hasattr(project, "exposed_ports")
        assert hasattr(project, "docker_compose")
        assert hasattr(project, "working_directory")
        assert hasattr(project, "environment_vars")
        assert hasattr(project, "registered_at")
        assert hasattr(project, "last_updated")
        assert hasattr(project, "status")
        
        # Check default values
        assert project.services == []
        assert project.service_ports == {}
        assert project.exposed_ports == []
        assert project.docker_compose is False
        assert project.environment_vars == {}
        assert project.status == "stopped"
    
    def test_register_project_creates_directory(self, mock_registry, tmp_gantry_home, tmp_path):
        """Test that project directory is created in ~/.gantry/projects/<hostname>/."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        project_dir = tmp_gantry_home / "projects" / "myproject"
        assert project_dir.is_dir()
    
    def test_register_project_atomic_write(self, mock_registry, tmp_gantry_home, tmp_path):
        """Test that registry writes are atomic (file integrity)."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        # Register project
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        # Verify registry file exists and is valid JSON (use patched path)
        projects_json = tmp_gantry_home / "projects.json"
        assert projects_json.exists()
        with open(projects_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "projects" in data
            assert "myproject" in data["projects"]
            assert data["projects"]["myproject"]["hostname"] == "myproject"
            assert data["projects"]["myproject"]["port"] == 5001


class TestGetProject:
    """Test get_project() method."""
    
    def test_get_existing_project(self, mock_registry, tmp_path):
        """Test retrieving an existing project."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        registered = mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        retrieved = mock_registry.get_project("myproject")
        
        assert retrieved is not None
        assert retrieved.hostname == registered.hostname
        assert retrieved.path == registered.path
        assert retrieved.port == registered.port
    
    def test_get_nonexistent_project(self, mock_registry):
        """Test retrieving a non-existent project returns None."""
        result = mock_registry.get_project("nonexistent")
        assert result is None


class TestListProjects:
    """Test list_projects() method."""
    
    def test_list_all_projects(self, mock_registry, tmp_path):
        """Test listing all registered projects."""
        # Register multiple projects
        for i in range(3):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5001 + i
            )
        
        projects = mock_registry.list_projects()
        
        assert len(projects) == 3
        hostnames = {p.hostname for p in projects}
        assert hostnames == {"project0", "project1", "project2"}
    
    def test_list_empty_registry(self, mock_registry):
        """Test listing projects when registry is empty."""
        projects = mock_registry.list_projects()
        assert projects == []


class TestUnregisterProject:
    """Test unregister_project() method."""
    
    def test_unregister_existing_project(self, mock_registry, tmp_gantry_home, tmp_path):
        """Test unregistering an existing project."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        # Verify project exists
        assert mock_registry.get_project("myproject") is not None
        
        # Unregister
        mock_registry.unregister_project("myproject")
        
        # Verify project is removed
        assert mock_registry.get_project("myproject") is None
        assert len(mock_registry.list_projects()) == 0
    
    def test_unregister_cleans_up_directory(self, mock_registry, tmp_gantry_home, tmp_path):
        """Test that unregistering cleans up project directory."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        project_dir = tmp_gantry_home / "projects" / "myproject"
        assert project_dir.is_dir()
        
        mock_registry.unregister_project("myproject")
        
        assert not project_dir.exists()
    
    def test_unregister_nonexistent_project_raises_error(self, mock_registry):
        """Test that unregistering a non-existent project raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            mock_registry.unregister_project("nonexistent")


class TestUpdateProjectStatus:
    """Test update_project_status() method."""
    
    def test_update_status_to_running(self, mock_registry, tmp_path):
        """Test updating project status to running."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        initial_time = mock_registry.get_project("myproject").last_updated
        
        # Update status
        mock_registry.update_project_status("myproject", "running")
        
        project = mock_registry.get_project("myproject")
        assert project.status == "running"
        assert project.last_updated > initial_time
    
    def test_update_status_to_stopped(self, mock_registry, tmp_path):
        """Test updating project status to stopped."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        mock_registry.update_project_status("myproject", "running")
        
        mock_registry.update_project_status("myproject", "stopped")
        
        project = mock_registry.get_project("myproject")
        assert project.status == "stopped"
    
    def test_update_status_to_error(self, mock_registry, tmp_path):
        """Test updating project status to error."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        mock_registry.update_project_status("myproject", "error")
        
        project = mock_registry.get_project("myproject")
        assert project.status == "error"


class TestUpdateProjectMetadata:
    """Test update_project_metadata() method."""
    
    def test_update_multiple_fields_atomically(self, mock_registry, tmp_path):
        """Test atomic updates of multiple fields."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        initial_time = mock_registry.get_project("myproject").last_updated
        
        # Update multiple fields
        mock_registry.update_project_metadata(
            "myproject",
            services=["app", "db"],
            service_ports={"app": 5001, "db": 5432},
            exposed_ports=[5001, 5432],
            docker_compose=True
        )
        
        project = mock_registry.get_project("myproject")
        assert project.services == ["app", "db"]
        assert project.service_ports == {"app": 5001, "db": 5432}
        assert project.exposed_ports == [5001, 5432]
        assert project.docker_compose is True
        assert project.last_updated > initial_time
    
    def test_update_always_updates_timestamp(self, mock_registry, tmp_path):
        """Test that last_updated timestamp always changes on update."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        initial_time = mock_registry.get_project("myproject").last_updated
        
        # Small delay to ensure timestamp difference
        import time
        time.sleep(0.01)
        
        # Update with same value
        mock_registry.update_project_metadata("myproject", status="stopped")
        
        updated_time = mock_registry.get_project("myproject").last_updated
        assert updated_time > initial_time
    
    def test_update_preserves_immutable_fields(self, mock_registry, tmp_path):
        """Test that immutable fields (hostname, registered_at, path) are preserved."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        registered = mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        original_hostname = registered.hostname
        original_registered_at = registered.registered_at
        original_path = registered.path
        
        # Try to update immutable fields (they should be ignored or raise error)
        mock_registry.update_project_metadata(
            "myproject",
            services=["app"]
        )
        
        project = mock_registry.get_project("myproject")
        assert project.hostname == original_hostname
        assert project.registered_at == original_registered_at
        assert project.path == original_path
    
    def test_update_nonexistent_project_raises_error(self, mock_registry):
        """Test that updating a non-existent project raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            mock_registry.update_project_metadata("nonexistent", status="running")


class TestGetRunningProjects:
    """Test get_running_projects() method."""
    
    def test_get_running_projects_filters_by_status(self, mock_registry, tmp_path):
        """Test that get_running_projects() filters by status='running'."""
        # Register multiple projects
        for i in range(3):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5001 + i
            )
        
        # Set some to running
        mock_registry.update_project_status("project0", "running")
        mock_registry.update_project_status("project1", "stopped")
        mock_registry.update_project_status("project2", "running")
        
        running = mock_registry.get_running_projects()
        
        assert len(running) == 2
        hostnames = {p.hostname for p in running}
        assert hostnames == {"project0", "project2"}
    
    def test_get_running_projects_empty_when_none_running(self, mock_registry, tmp_path):
        """Test that get_running_projects() returns empty list when no projects are running."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        running = mock_registry.get_running_projects()
        assert running == []


class TestUpdateServicePorts:
    """Test update_service_ports() method."""
    
    def test_update_service_ports_updates_both_fields(self, mock_registry, tmp_path):
        """Test that update_service_ports() updates both service_ports and exposed_ports."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        mock_registry.update_service_ports(
            "myproject",
            service_ports={"postgres": 5432, "redis": 6379},
            exposed_ports=[5001, 5432, 6379]
        )
        
        project = mock_registry.get_project("myproject")
        assert project.service_ports == {"postgres": 5432, "redis": 6379}
        assert set(project.exposed_ports) == {5001, 5432, 6379}
