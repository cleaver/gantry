from typing import Dict, List
import logging
import time

from .registry import Registry
from .process_manager import ProcessManager


class Orchestrator:
    """
    Orchestrates management of multiple projects.
    Handles stopping all services, status aggregation, and monitoring.
    """

    def __init__(self, registry: Registry, process_manager: ProcessManager):
        self._registry = registry
        self._process_manager = process_manager

    def stop_all(self) -> List[str]:
        """
        Gracefully stop all currently running projects.

        Returns:
            List of hostnames that were successfully stopped.
        """
        stopped_projects = []
        # Get a snapshot of running projects
        running_projects = self._registry.get_running_projects()

        for project in running_projects:
            try:
                logging.info(f"Stopping project '{project.hostname}'...")
                self._process_manager.stop_project(project.hostname)
                stopped_projects.append(project.hostname)
            except Exception as e:
                logging.error(f"Failed to stop project '{project.hostname}': {e}")
                # We continue trying to stop other projects even if one fails

        return stopped_projects

    def get_all_status(self) -> Dict[str, str]:
        """
        Get the current status of all registered projects.
        This triggers a live check via ProcessManager for each project,
        which updates the registry if the status has changed.

        Returns:
            Dictionary mapping hostname -> status string ("running", "stopped", "error")
        """
        projects = self._registry.list_projects()
        statuses = {}

        for project in projects:
            try:
                # get_status() updates the registry as a side effect
                status = self._process_manager.get_status(project.hostname)
                statuses[project.hostname] = status
            except Exception as e:
                logging.error(f"Failed to get status for '{project.hostname}': {e}")
                statuses[project.hostname] = "error"

        return statuses

    def watch_services(self, interval: int = 60, single_run: bool = False):
        """
        Monitor health of running services (Background Loop).

        Args:
            interval: Time in seconds between checks.
            single_run: If True, performs one check pass and returns (useful for testing).
        """
        while True:
            try:
                running_projects = self._registry.get_running_projects()
                for project in running_projects:
                    try:
                        # First check if it's still running at process level
                        status = self._process_manager.get_status(project.hostname)

                        if status == "running":
                            # Perform application-level health check
                            is_healthy = self._process_manager.health_check(
                                project.hostname
                            )
                            if not is_healthy:
                                logging.warning(
                                    f"Project '{project.hostname}' failed health check."
                                )
                                # Future: Implement auto-restart policy here

                    except Exception as e:
                        logging.error(
                            f"Error monitoring project '{project.hostname}': {e}"
                        )

            except Exception as e:
                logging.error(f"Error in watch_services loop: {e}")

            if single_run:
                break

            time.sleep(interval)
