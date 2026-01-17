"""Tests for routing configuration generation."""

from pathlib import Path

import pytest

from gantry.registry import Project
from gantry.routing_config import generate_routes_for_project


@pytest.fixture
def sample_project():
    """Create a sample project for testing."""
    return Project(
        hostname="testproj",
        path=Path("/tmp/testproj"),
        port=5001,
        service_ports={"db": 5432, "redis": 6379},
        exposed_ports=[5001, 5432, 6379],
        services=["web", "db", "redis"],
        docker_compose=True,
        status="stopped",
        working_directory=Path("/tmp/testproj"),
        environment_vars={},
        registered_at="2023-01-01T12:00:00Z",
        last_started=None,
        last_updated="2023-01-01T12:00:00Z",
    )


class TestGenerateRoutesForProject:
    """Test generate_routes_for_project() function."""

    def test_basic_project_single_port(self):
        """Test routing generation for basic project with single port."""
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
            last_updated="2023-01-01T12:00:00Z",
        )

        routes = generate_routes_for_project(project)

        assert len(routes) == 1
        assert routes[0]["domain"] == "simple.test"
        assert routes[0]["port"] == 5001

    def test_project_with_multiple_services(self, sample_project):
        """Test routing generation for project with multiple services."""
        routes = generate_routes_for_project(sample_project)

        # Should have main route + 2 service routes
        assert len(routes) == 3

        # Main route should be first
        assert routes[0]["domain"] == "testproj.test"
        assert routes[0]["port"] == 5001

        # Service routes should follow
        service_domains = [r["domain"] for r in routes[1:]]
        service_ports = [r["port"] for r in routes[1:]]

        assert "db.testproj.test" in service_domains
        assert "redis.testproj.test" in service_domains
        assert 5432 in service_ports
        assert 6379 in service_ports

    def test_service_port_deduplication(self):
        """Test that service ports matching project port are not duplicated."""
        project = Project(
            hostname="dedup",
            path=Path("/tmp/dedup"),
            port=5001,
            service_ports={"web": 5001, "api": 5002},  # web port matches main port
            exposed_ports=[5001, 5002],
            services=["web", "api"],
            docker_compose=True,
            status="stopped",
            working_directory=Path("/tmp/dedup"),
            environment_vars={},
            registered_at="2023-01-01T12:00:00Z",
            last_started=None,
            last_updated="2023-01-01T12:00:00Z",
        )

        routes = generate_routes_for_project(project)

        # Should have main route + 1 service route (web is deduplicated)
        assert len(routes) == 2

        # Main route
        assert routes[0]["domain"] == "dedup.test"
        assert routes[0]["port"] == 5001

        # Only api service route (web is skipped)
        assert routes[1]["domain"] == "api.dedup.test"
        assert routes[1]["port"] == 5002

        # Verify web service is not in routes
        domains = [r["domain"] for r in routes]
        assert "web.dedup.test" not in domains

    def test_project_no_services(self):
        """Test routing generation for project with no services."""
        project = Project(
            hostname="noservices",
            path=Path("/tmp/noservices"),
            port=5001,
            service_ports={},
            exposed_ports=[5001],
            services=[],
            docker_compose=False,
            status="stopped",
            working_directory=Path("/tmp/noservices"),
            environment_vars={},
            registered_at="2023-01-01T12:00:00Z",
            last_started=None,
            last_updated="2023-01-01T12:00:00Z",
        )

        routes = generate_routes_for_project(project)

        # Should only have main route
        assert len(routes) == 1
        assert routes[0]["domain"] == "noservices.test"
        assert routes[0]["port"] == 5001

    def test_project_no_port(self):
        """Test routing generation for project with no main port."""
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
            last_updated="2023-01-01T12:00:00Z",
        )

        routes = generate_routes_for_project(project)

        # Should only have service route (no main route)
        assert len(routes) == 1
        assert routes[0]["domain"] == "db.noport.test"
        assert routes[0]["port"] == 5432

    def test_project_no_port_no_services(self):
        """Test routing generation for project with no port and no services."""
        project = Project(
            hostname="empty",
            path=Path("/tmp/empty"),
            port=None,
            service_ports={},
            exposed_ports=[],
            services=[],
            docker_compose=False,
            status="stopped",
            working_directory=Path("/tmp/empty"),
            environment_vars={},
            registered_at="2023-01-01T12:00:00Z",
            last_started=None,
            last_updated="2023-01-01T12:00:00Z",
        )

        routes = generate_routes_for_project(project)

        # Should have no routes
        assert len(routes) == 0
        assert routes == []

    def test_route_structure(self, sample_project):
        """Test that routes have correct structure (domain and port keys)."""
        routes = generate_routes_for_project(sample_project)

        for route in routes:
            assert "domain" in route
            assert "port" in route
            assert isinstance(route["domain"], str)
            assert isinstance(route["port"], int)
            assert route["domain"].endswith(".test")
            assert route["port"] > 0

    def test_domain_name_generation(self):
        """Test domain name generation format."""
        project = Project(
            hostname="myapp",
            path=Path("/tmp/myapp"),
            port=5001,
            service_ports={"api": 5002, "admin": 5003},
            exposed_ports=[5001, 5002, 5003],
            services=["web", "api", "admin"],
            docker_compose=True,
            status="stopped",
            working_directory=Path("/tmp/myapp"),
            environment_vars={},
            registered_at="2023-01-01T12:00:00Z",
            last_started=None,
            last_updated="2023-01-01T12:00:00Z",
        )

        routes = generate_routes_for_project(project)

        # Check main domain format
        assert routes[0]["domain"] == "myapp.test"

        # Check service domain format
        domains = [r["domain"] for r in routes[1:]]
        assert "api.myapp.test" in domains
        assert "admin.myapp.test" in domains

    def test_route_ordering(self, sample_project):
        """Test that main route comes first, then services."""
        routes = generate_routes_for_project(sample_project)

        # First route should be main route
        assert routes[0]["domain"] == "testproj.test"
        assert routes[0]["port"] == sample_project.port

        # Subsequent routes should be services (format: service.hostname.test)
        for route in routes[1:]:
            # Should not be just hostname.test (that's the main route)
            assert route["domain"] != f"{sample_project.hostname}.test"
            # Should contain hostname as subdomain
            assert f".{sample_project.hostname}.test" in route["domain"]
            # Should have service name before hostname
            assert route["domain"].count(".") == 2  # service.hostname.test

    def test_multiple_services_same_port(self):
        """Test routing with multiple services sharing the same port."""
        project = Project(
            hostname="shared",
            path=Path("/tmp/shared"),
            port=5001,
            service_ports={"service1": 5002, "service2": 5002},  # Same port
            exposed_ports=[5001, 5002],
            services=["web", "service1", "service2"],
            docker_compose=True,
            status="stopped",
            working_directory=Path("/tmp/shared"),
            environment_vars={},
            registered_at="2023-01-01T12:00:00Z",
            last_started=None,
            last_updated="2023-01-01T12:00:00Z",
        )

        routes = generate_routes_for_project(project)

        # Should have main route + 2 service routes (both pointing to same port)
        assert len(routes) == 3

        # Both services should have routes
        domains = [r["domain"] for r in routes]
        assert "service1.shared.test" in domains
        assert "service2.shared.test" in domains

        # Both should point to same port
        ports = {r["domain"]: r["port"] for r in routes}
        assert ports["service1.shared.test"] == 5002
        assert ports["service2.shared.test"] == 5002
