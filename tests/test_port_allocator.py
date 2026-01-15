"""Tests for port allocation, detection, and conflict checking."""
import socket
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from gantry.port_allocator import PortAllocator, PortConflictError
from gantry.registry import Registry


class TestIsPortAvailable:
    """Test is_port_available() method."""
    
    def test_port_available_when_free(self, port_allocator):
        """Test that a free port returns True."""
        # Use a high port number that's unlikely to be in use
        result = port_allocator.is_port_available(5999)
        assert result is True
    
    def test_port_unavailable_when_in_use(self, port_allocator, monkeypatch):
        """Test that a port in use returns False."""
        # Mock socket to raise error on bind
        def mock_bind(address):
            raise socket.error("Address already in use")
        
        original_socket = __import__("socket").socket
        
        class MockSocket:
            def __init__(self, *args, **kwargs):
                self.settimeout_called = False
                self.bind_called = False
            
            def settimeout(self, timeout):
                self.settimeout_called = True
            
            def bind(self, address):
                raise socket.error("Address already in use")
            
            def __enter__(self):
                return self
            
            def __exit__(self, *args):
                pass
        
        import socket
        monkeypatch.setattr("gantry.port_allocator.socket.socket", lambda *args, **kwargs: MockSocket())
        
        result = port_allocator.is_port_available(5001)
        assert result is False
    
    def test_invalid_port_number(self, port_allocator):
        """Test handling of invalid port numbers."""
        # Ports outside valid range - socket.bind may not raise for all invalid ports
        # but should return False or handle gracefully
        # Negative ports should fail
        result_neg = port_allocator.is_port_available(-1)
        # Very large ports might raise or return False depending on system
        try:
            result_large = port_allocator.is_port_available(70000)
            # If no exception, should return False
            assert result_large is False
        except (OverflowError, OSError, ValueError):
            # Exception is also acceptable
            pass


class TestAllocatePort:
    """Test allocate_port() method."""
    
    def test_allocate_first_available_port(self, port_allocator, mock_registry):
        """Test that allocate_port() finds the first available port in range."""
        port = port_allocator.allocate_port()
        assert 5000 <= port < 6000
    
    def test_allocate_skips_allocated_ports(self, port_allocator, mock_registry, tmp_path):
        """Test that allocate_port() skips ports already allocated to projects."""
        # Register a project with a specific port
        project_path = tmp_path / "project1"
        project_path.mkdir()
        project = mock_registry.register_project(
            hostname="project1",
            path=project_path,
            port=5001
        )
        mock_registry.update_project_metadata(
            "project1",
            exposed_ports=[5001]
        )
        
        # Allocate should skip 5001
        allocated = port_allocator.allocate_port()
        assert allocated != 5001
        assert 5000 <= allocated < 6000
    
    def test_allocate_skips_system_ports(self, port_allocator, monkeypatch):
        """Test that allocate_port() skips ports in use by system."""
        # Mock is_port_available to return False for specific ports
        unavailable_ports = {5000, 5001, 5002}
        
        original_is_available = port_allocator.is_port_available
        
        def mock_is_available(port):
            if port in unavailable_ports:
                return False
            return original_is_available(port)
        
        port_allocator.is_port_available = mock_is_available
        
        allocated = port_allocator.allocate_port()
        assert allocated not in unavailable_ports
        assert 5000 <= allocated < 6000
    
    @pytest.mark.slow
    def test_allocate_raises_error_when_no_ports_available(self, port_allocator, mock_registry, tmp_path):
        """Test that allocate_port() raises RuntimeError when no ports available."""
        # Fill up all ports in range
        for i in range(1000):  # 5000-5999 = 1000 ports
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            project = mock_registry.register_project(
                hostname=f"project{i}",
                path=project_path,
                port=5000 + i
            )
            mock_registry.update_project_metadata(
                f"project{i}",
                exposed_ports=[5000 + i]
            )
        
        # Mock is_port_available to return False for all
        port_allocator.is_port_available = lambda p: False
        
        with pytest.raises(RuntimeError, match="No available ports"):
            port_allocator.allocate_port()


class TestGetProjectPort:
    """Test get_project_port() method."""
    
    def test_get_port_for_existing_project(self, port_allocator, mock_registry, tmp_path):
        """Test getting port for an existing project."""
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        mock_registry.register_project(
            hostname="myproject",
            path=project_path,
            port=5001
        )
        
        port = port_allocator.get_project_port("myproject")
        assert port == 5001
    
    def test_get_port_for_nonexistent_project(self, port_allocator):
        """Test getting port for non-existent project returns None."""
        port = port_allocator.get_project_port("nonexistent")
        assert port is None


class TestDetectServicePorts:
    """Test detect_service_ports() method with various docker-compose formats."""
    
    def test_detect_ports_short_syntax(self, port_allocator, tmp_path):
        """Test detecting ports with short syntax 'HOST:CONTAINER'."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_data = {
            "services": {
                "postgres": {
                    "ports": ["5432:5432"]
                },
                "redis": {
                    "ports": ["6379:6379"]
                }
            }
        }
        with open(compose_file, "w", encoding="utf-8") as f:
            yaml.dump(compose_data, f)
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        assert ports == {"postgres": 5432, "redis": 6379}
    
    def test_detect_ports_long_syntax(self, port_allocator, tmp_path):
        """Test detecting ports with long syntax using 'published' field."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_data = {
            "services": {
                "postgres": {
                    "ports": [
                        {
                            "target": 5432,
                            "published": 5432,
                            "protocol": "tcp"
                        }
                    ]
                },
                "redis": {
                    "ports": [
                        {
                            "target": 6379,
                            "published": 6379,
                            "protocol": "tcp"
                        }
                    ]
                }
            }
        }
        with open(compose_file, "w", encoding="utf-8") as f:
            yaml.dump(compose_data, f)
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        assert ports == {"postgres": 5432, "redis": 6379}
    
    def test_detect_ports_mixed_syntax(self, port_allocator, tmp_path):
        """Test detecting ports with mixed short and long syntax."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_data = {
            "services": {
                "mailhog_smtp": {
                    "ports": ["1025:1025"]
                },
                "mailhog_web": {
                    "ports": [
                        {
                            "target": 8025,
                            "published": 8025,
                            "protocol": "tcp"
                        }
                    ]
                }
            }
        }
        with open(compose_file, "w", encoding="utf-8") as f:
            yaml.dump(compose_data, f)
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        assert ports == {"mailhog_smtp": 1025, "mailhog_web": 8025}
    
    def test_detect_ports_multiple_ports_per_service(self, port_allocator, tmp_path):
        """Test that only first port is used when service has multiple ports."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_data = {
            "services": {
                "app": {
                    "ports": ["5001:5001", "5002:5002", "8080:80"]
                }
            }
        }
        with open(compose_file, "w", encoding="utf-8") as f:
            yaml.dump(compose_data, f)
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        # Should only use first port
        assert ports == {"app": 5001}
    
    def test_detect_ports_missing_file(self, port_allocator, tmp_path):
        """Test handling of missing docker-compose.yml file."""
        compose_file = tmp_path / "nonexistent.yml"
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        assert ports == {}
    
    def test_detect_ports_services_without_ports(self, port_allocator, tmp_path):
        """Test handling of services without port mappings."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_data = {
            "services": {
                "app": {
                    "image": "nginx"
                },
                "db": {
                    "image": "postgres"
                }
            }
        }
        with open(compose_file, "w", encoding="utf-8") as f:
            yaml.dump(compose_data, f)
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        assert ports == {}
    
    def test_detect_ports_empty_yaml(self, port_allocator, tmp_path):
        """Test handling of empty YAML file."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("")
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        assert ports == {}
    
    def test_detect_ports_malformed_yaml(self, port_allocator, tmp_path):
        """Test handling of malformed YAML."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("invalid: yaml: content: [")
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        assert ports == {}
    
    def test_detect_ports_different_host_port(self, port_allocator, tmp_path):
        """Test detecting ports when host and container ports differ."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_data = {
            "services": {
                "app": {
                    "ports": ["8080:80"]  # Host 8080, container 80
                }
            }
        }
        with open(compose_file, "w", encoding="utf-8") as f:
            yaml.dump(compose_data, f)
        
        ports = port_allocator.detect_service_ports(compose_file)
        
        # Should return host port (8080), not container port (80)
        assert ports == {"app": 8080}


class TestCheckPortConflicts:
    """Test check_port_conflicts() method."""
    
    def test_no_conflicts_when_none_running(self, port_allocator, mock_registry):
        """Test that check_port_conflicts() returns empty list when no conflicts."""
        conflicts = port_allocator.check_port_conflicts("project1", [5001, 5002])
        assert conflicts == []
    
    def test_detect_conflicts_with_running_projects(self, port_allocator, mock_registry, tmp_path):
        """Test detecting conflicts with running projects."""
        # Register and set project1 as running with ports
        project1_path = tmp_path / "project1"
        project1_path.mkdir()
        mock_registry.register_project("project1", project1_path, port=5001)
        mock_registry.update_project_metadata(
            "project1",
            status="running",
            service_ports={"http": 5001, "db": 5432},
            exposed_ports=[5001, 5432]
        )
        
        # Register project2 as running with overlapping port
        project2_path = tmp_path / "project2"
        project2_path.mkdir()
        mock_registry.register_project("project2", project2_path, port=5003)
        mock_registry.update_project_metadata(
            "project2",
            status="running",
            service_ports={"http": 5003, "db": 5432},  # Same db port
            exposed_ports=[5003, 5432]
        )
        
        # Check conflicts for a new project trying to use port 5432
        conflicts = port_allocator.check_port_conflicts("newproject", [5432])
        
        assert len(conflicts) == 2  # Both project1 and project2 use 5432
        conflict_ports = {c["port"] for c in conflicts}
        assert conflict_ports == {5432}
        conflict_projects = {c["conflicting_project"] for c in conflicts}
        assert conflict_projects == {"project1", "project2"}
    
    def test_skip_self_when_checking_conflicts(self, port_allocator, mock_registry, tmp_path):
        """Test that check_port_conflicts() skips self when checking."""
        project_path = tmp_path / "project1"
        project_path.mkdir()
        mock_registry.register_project("project1", project_path, port=5001)
        mock_registry.update_project_metadata(
            "project1",
            status="running",
            exposed_ports=[5001, 5432]
        )
        
        # Check conflicts for project1 itself
        conflicts = port_allocator.check_port_conflicts("project1", [5001, 5432])
        
        # Should not conflict with itself
        assert conflicts == []
    
    def test_conflict_information_includes_service(self, port_allocator, mock_registry, tmp_path):
        """Test that conflict information includes service name."""
        project_path = tmp_path / "project1"
        project_path.mkdir()
        mock_registry.register_project("project1", project_path, port=5001)
        mock_registry.update_project_metadata(
            "project1",
            status="running",
            service_ports={"postgres": 5432},
            exposed_ports=[5001, 5432]
        )
        
        conflicts = port_allocator.check_port_conflicts("newproject", [5432])
        
        assert len(conflicts) == 1
        assert conflicts[0]["port"] == 5432
        assert conflicts[0]["conflicting_project"] == "project1"
        assert conflicts[0]["service"] == "postgres"
    
    def test_multiple_conflicts(self, port_allocator, mock_registry, tmp_path):
        """Test handling of multiple port conflicts."""
        project_path = tmp_path / "project1"
        project_path.mkdir()
        mock_registry.register_project("project1", project_path, port=5001)
        mock_registry.update_project_metadata(
            "project1",
            status="running",
            service_ports={"http": 5001, "db": 5432, "redis": 6379},
            exposed_ports=[5001, 5432, 6379]
        )
        
        conflicts = port_allocator.check_port_conflicts("newproject", [5001, 5432, 6379])
        
        assert len(conflicts) == 3
        conflict_ports = {c["port"] for c in conflicts}
        assert conflict_ports == {5001, 5432, 6379}


class TestValidateStartupPorts:
    """Test validate_startup_ports() method."""
    
    def test_validation_passes_when_no_conflicts(self, port_allocator, mock_registry, tmp_path):
        """Test that validation passes when no conflicts exist."""
        project_path = tmp_path / "project1"
        project_path.mkdir()
        mock_registry.register_project("project1", project_path, port=5001)
        mock_registry.update_project_metadata(
            "project1",
            exposed_ports=[5001]
        )
        
        # Should not raise
        port_allocator.validate_startup_ports("project1")
    
    def test_validation_raises_error_with_conflicts(self, port_allocator, mock_registry, tmp_path):
        """Test that validation raises PortConflictError when conflicts exist."""
        # Register project1 as running
        project1_path = tmp_path / "project1"
        project1_path.mkdir()
        mock_registry.register_project("project1", project1_path, port=5001)
        mock_registry.update_project_metadata(
            "project1",
            status="running",
            exposed_ports=[5001, 5432]
        )
        
        # Register project2 with conflicting port
        project2_path = tmp_path / "project2"
        project2_path.mkdir()
        mock_registry.register_project("project2", project2_path, port=5003)
        mock_registry.update_project_metadata(
            "project2",
            exposed_ports=[5003, 5432]  # Conflicts with project1's 5432
        )
        
        with pytest.raises(PortConflictError) as exc_info:
            port_allocator.validate_startup_ports("project2")
        
        assert len(exc_info.value.conflicts) > 0
    
    def test_validation_raises_error_for_nonexistent_project(self, port_allocator):
        """Test that validation raises ValueError for non-existent project."""
        with pytest.raises(ValueError, match="not found"):
            port_allocator.validate_startup_ports("nonexistent")


class TestGetRunningProjectPorts:
    """Test get_running_project_ports() method."""
    
    def test_get_running_project_ports(self, port_allocator, mock_registry, tmp_path):
        """Test getting ports for running projects."""
        # Register multiple projects
        for i in range(3):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(f"project{i}", project_path, port=5001 + i)
            status = "running" if i < 2 else "stopped"
            mock_registry.update_project_metadata(
                f"project{i}",
                status=status,
                exposed_ports=[5001 + i, 5432 + i]
            )
        
        running_ports = port_allocator.get_running_project_ports()
        
        assert len(running_ports) == 2
        assert "project0" in running_ports
        assert "project1" in running_ports
        assert "project2" not in running_ports
        assert running_ports["project0"] == [5001, 5432]
        assert running_ports["project1"] == [5002, 5433]
    
    def test_get_running_project_ports_empty_when_none_running(self, port_allocator, mock_registry, tmp_path):
        """Test that get_running_project_ports() returns empty dict when no projects running."""
        project_path = tmp_path / "project1"
        project_path.mkdir()
        mock_registry.register_project("project1", project_path, port=5001)
        mock_registry.update_project_metadata(
            "project1",
            status="stopped",
            exposed_ports=[5001]
        )
        
        running_ports = port_allocator.get_running_project_ports()
        
        assert running_ports == {}


class TestGetPortUsage:
    """Test get_port_usage() method."""
    
    def test_get_port_usage_maps_ports_to_projects(self, port_allocator, mock_registry, tmp_path):
        """Test that get_port_usage() maps ports to projects using them."""
        # Register multiple projects with different ports
        project1_path = tmp_path / "project1"
        project1_path.mkdir()
        mock_registry.register_project("project1", project1_path, port=5001)
        mock_registry.update_project_metadata(
            "project1",
            exposed_ports=[5001, 5432]
        )
        
        project2_path = tmp_path / "project2"
        project2_path.mkdir()
        mock_registry.register_project("project2", project2_path, port=5002)
        mock_registry.update_project_metadata(
            "project2",
            exposed_ports=[5002, 5432]  # Shared port with project1
        )
        
        usage = port_allocator.get_port_usage()
        
        assert 5001 in usage
        assert "project1" in usage[5001]
        assert 5002 in usage
        assert "project2" in usage[5002]
        assert 5432 in usage
        assert "project1" in usage[5432]
        assert "project2" in usage[5432]
    
    def test_get_port_usage_handles_multiple_projects_same_port(self, port_allocator, mock_registry, tmp_path):
        """Test that get_port_usage() handles multiple projects using same port."""
        # Register multiple projects with same port
        for i in range(3):
            project_path = tmp_path / f"project{i}"
            project_path.mkdir()
            mock_registry.register_project(f"project{i}", project_path, port=5001 + i)
            mock_registry.update_project_metadata(
                f"project{i}",
                exposed_ports=[5432]  # All use same port
            )
        
        usage = port_allocator.get_port_usage()
        
        assert 5432 in usage
        assert len(usage[5432]) == 3
        assert set(usage[5432]) == {"project0", "project1", "project2"}
    
    def test_get_port_usage_empty_when_no_projects(self, port_allocator):
        """Test that get_port_usage() returns empty dict when no projects."""
        usage = port_allocator.get_port_usage()
        assert usage == {}
