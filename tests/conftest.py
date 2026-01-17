"""Shared fixtures and utilities for Gantry tests."""

import os
import socket
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest
import yaml

from gantry.port_allocator import PortAllocator
from gantry.registry import GANTRY_HOME, PROJECTS_JSON, Registry


@pytest.fixture
def tmp_gantry_home(tmp_path, monkeypatch):
    """Create a temporary directory for ~/.gantry and patch the global constants."""
    gantry_home = tmp_path / ".gantry"
    gantry_home.mkdir()
    (gantry_home / "projects").mkdir()

    # Patch the global constants in the registry module
    monkeypatch.setattr("gantry.registry.GANTRY_HOME", gantry_home)
    monkeypatch.setattr("gantry.registry.PROJECTS_JSON", gantry_home / "projects.json")

    return gantry_home


@pytest.fixture
def mock_registry(tmp_gantry_home):
    """Create a Registry instance with temporary home directory."""
    return Registry()


@pytest.fixture
def sample_project_path(tmp_path):
    """Create a temporary directory with sample project files."""
    project_path = tmp_path / "sample_project"
    project_path.mkdir()
    return project_path


@pytest.fixture
def sample_compose_file(sample_project_path):
    """Helper to create docker-compose.yml files with various formats."""

    def _create_compose_file(content: Dict) -> Path:
        """Create a docker-compose.yml file with the given content."""
        compose_file = sample_project_path / "docker-compose.yml"
        with open(compose_file, "w", encoding="utf-8") as f:
            yaml.dump(content, f)
        return compose_file

    return _create_compose_file


@pytest.fixture
def mock_port_available(monkeypatch):
    """Mock for is_port_available() to control port availability."""
    available_ports = set()

    def _is_port_available(port: int) -> bool:
        """Mock implementation that checks against available_ports set."""
        # Check if port is in the available set
        if port in available_ports:
            return True

        # Also check if it's in the valid range
        if not (5000 <= port < 6000):
            return False

        # Default: port is available unless explicitly marked as unavailable
        return True

    def _mark_port_unavailable(port: int):
        """Mark a port as unavailable."""
        available_ports.discard(port)

    def _mark_port_available(port: int):
        """Mark a port as available."""
        available_ports.add(port)

    # Create a mock that wraps the real socket check but can be controlled
    original_socket = socket.socket

    def mock_socket(*args, **kwargs):
        sock = original_socket(*args, **kwargs)

        original_bind = sock.bind

        def mock_bind(address):
            port = address[1]
            if port not in available_ports and 5000 <= port < 6000:
                # Check if we should allow this port
                # By default, allow all ports in range unless explicitly blocked
                try:
                    return original_bind(address)
                except (socket.error, OverflowError):
                    raise
            else:
                # Port is explicitly marked as unavailable
                raise socket.error(f"Port {port} is not available")

        sock.bind = mock_bind
        return sock

    monkeypatch.setattr("socket.socket", mock_socket)

    return {
        "is_available": _is_port_available,
        "mark_unavailable": _mark_port_unavailable,
        "mark_available": _mark_port_available,
    }


@pytest.fixture
def port_allocator(mock_registry):
    """Create a PortAllocator instance with a mock registry."""
    return PortAllocator(mock_registry)


def create_compose_file_short_syntax(path: Path, services: Dict[str, Dict]) -> Path:
    """Create a docker-compose.yml with short port syntax."""
    compose_data = {"services": services}
    compose_file = path / "docker-compose.yml"
    with open(compose_file, "w", encoding="utf-8") as f:
        yaml.dump(compose_data, f)
    return compose_file


def create_compose_file_long_syntax(path: Path, services: Dict[str, Dict]) -> Path:
    """Create a docker-compose.yml with long port syntax."""
    compose_data = {"services": services}
    compose_file = path / "docker-compose.yml"
    with open(compose_file, "w", encoding="utf-8") as f:
        yaml.dump(compose_data, f)
    return compose_file


def create_compose_file_mixed_syntax(path: Path, services: Dict[str, Dict]) -> Path:
    """Create a docker-compose.yml with mixed port syntax."""
    compose_data = {"services": services}
    compose_file = path / "docker-compose.yml"
    with open(compose_file, "w", encoding="utf-8") as f:
        yaml.dump(compose_data, f)
    return compose_file
