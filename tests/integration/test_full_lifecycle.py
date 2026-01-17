"""
End-to-end integration tests for Gantry.
These tests run in a real Linux environment inside a Docker container.
They test the ACTUAL CLI commands and verify side effects on the system.
"""

import os
import subprocess
import time
from pathlib import Path
import pytest
from typer.testing import CliRunner
from gantry.cli import app
from gantry.registry import Registry

runner = CliRunner()


@pytest.mark.skipif(
    not os.getenv("GANTRY_INTEGRATION_TEST"),
    reason="Only runs in integration test container",
)
class TestFullLifecycle:
    """Tests the entire flow from registration to proxy resolution."""

    def test_end_to_end_project_flow(self, tmp_path, integration_registry):
        """
        Flow: Register -> Start -> Verify DNS -> Verify Caddy -> Stop
        """
        # 1. Setup a dummy project directory with a docker-compose file
        project_name = "integration-app"
        project_dir = tmp_path / project_name
        project_dir.mkdir()

        compose_content = """
services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
"""
        (project_dir / "docker-compose.yml").write_text(compose_content)

        # 2. Register via CLI
        result = runner.invoke(
            app,
            [
                "register",
                "--hostname",
                project_name,
                "--path",
                str(project_dir),
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "registered successfully" in result.stdout

        # 3. Setup DNS (requires sudo in container)
        # Note: In the integration container, sudo is configured to be passwordless
        dns_result = runner.invoke(app, ["dns", "setup"])
        assert dns_result.exit_code == 0

        # Verify DNS file exists on the actual filesystem
        assert Path("/etc/dnsmasq.d/gantry.conf").exists()

        # 4. Start the project
        start_result = runner.invoke(app, ["start", project_name])
        assert start_result.exit_code == 0

        # Wait for Docker containers to spin up
        time.sleep(5)

        # 5. Verify local connectivity (direct to port)
        project = integration_registry.get_project(project_name)
        port = project.port
        check_cmd = subprocess.run(
            ["curl", "-s", "-f", f"http://localhost:{port}"], capture_output=True
        )
        assert check_cmd.returncode == 0
        assert "Welcome to nginx" in check_cmd.stdout.decode()

        # 6. Verify DNS resolution
        # We check if anything.test resolves to 127.0.0.1 via getent
        # This confirms our dnsmasq config is being respected by the system
        res_cmd = subprocess.run(
            ["getent", "hosts", f"{project_name}.test"], capture_output=True, text=True
        )
        assert "127.0.0.1" in res_cmd.stdout

        # 7. Stop the project
        stop_result = runner.invoke(app, ["stop", project_name])
        assert stop_result.exit_code == 0

        # Verify containers are actually gone
        ps_cmd = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        assert (
            project_name not in ps_cmd.stdout
            or '"State":"running"' not in ps_cmd.stdout
        )

    def test_port_conflict_prevention(self, tmp_path):
        """Verify that two projects cannot start if they share an exposed host port."""
        # Create project A using port 9001
        dir_a = tmp_path / "proj_a"
        dir_a.mkdir()
        (dir_a / "docker-compose.yml").write_text(
            "services:\n  db:\n    image: postgres:alpine\n    ports:\n      - '9001:5432'"
        )

        # Create project B also using port 9001
        dir_b = tmp_path / "proj_b"
        dir_b.mkdir()
        (dir_b / "docker-compose.yml").write_text(
            "services:\n  db:\n    image: redis:alpine\n    ports:\n      - '9001:6379'"
        )

        runner.invoke(
            app, ["register", "--hostname", "proja", "--path", str(dir_a), "--yes"]
        )
        runner.invoke(
            app, ["register", "--hostname", "projb", "--path", str(dir_b), "--yes"]
        )

        # Start A
        runner.invoke(app, ["start", "proja"])

        # Attempt to start B - should fail due to conflict
        start_b = runner.invoke(app, ["start", "projb"])
        assert start_b.exit_code != 0
        assert "Port conflict" in start_b.stdout
