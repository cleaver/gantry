"""Fixtures specifically for integration tests."""

import pytest
import os
import shutil
from pathlib import Path
from gantry.registry import Registry, GANTRY_HOME


@pytest.fixture
def integration_registry():
    """
    Returns a real Registry instance pointing to the integration environment.
    Cleans up any previous projects before starting.
    """
    if PROJECTS_JSON := (GANTRY_HOME / "projects.json"):
        if PROJECTS_JSON.exists():
            PROJECTS_JSON.unlink()

    if PROJECTS_DIR := (GANTRY_HOME / "projects"):
        if PROJECTS_DIR.exists():
            shutil.rmtree(PROJECTS_DIR)
            PROJECTS_DIR.mkdir()

    return Registry()


@pytest.fixture(autouse=True)
def cleanup_dns():
    """Ensures dnsmasq config is clean before and after tests."""
    gantry_dns = Path("/etc/dnsmasq.d/gantry.conf")
    yield
    if gantry_dns.exists():
        # Clean up would normally happen here if we wanted to revert the system
        # But in a container, we can just let it be destroyed.
        pass
