# Using uv for Gantry Development

This guide provides instructions for using `uv` to set up and manage the development environment for Gantry. `uv` is a fast, modern Python package manager that is used for dependency management and virtual environments in this project.

## Initial Development Setup

To get started with developing Gantry, you need to create a virtual environment and install the project in "editable" mode. This means your changes to the source code will be reflected immediately when you run the `gantry` command.

Follow these steps from the root of the `gantry` project directory:

1.  **Create the Virtual Environment:**
    This command creates a new virtual environment in a directory named `.venv`.
    ```bash
    uv venv
    ```

2.  **Activate the Virtual Environment:**
    You must activate the environment to make the `gantry` command and its dependencies available in your shell.
    ```bash
    source .venv/bin/activate
    ```
    Your shell prompt should change to indicate that the environment is active (e.g., `(.venv) ...`).

3.  **Install Dependencies in Editable Mode:**
    This command installs Gantry in editable (`-e`) mode, along with all development dependencies (`[dev]`).
    ```bash
    uv pip install -e ".[dev]"
    ```

After these steps, the `gantry` command will be available as long as your virtual environment is active.

## Daily Development Workflow

For each new terminal session where you want to work on Gantry, you must reactivate the virtual environment:

```bash
# Navigate to the gantry project directory
cd /path/to/gantry

# Activate the environment
source .venv/bin/activate
```

Once activated, you can run `gantry` from any directory.

## Installing as a Tool (Not for Development)

If you want to install and *use* Gantry like a regular command-line application (without needing to activate the virtual environment), you can use `uv tool install`.

**Note:** This is **not** recommended for active development, as code changes are not reflected automatically.

```bash
# Run from the gantry project root
uv tool install .
```

This installs the `gantry` command to a shared binary location (`~/.local/bin`), which should be in your system's `PATH`.

## Common `uv` Commands

-   **Sync Dependencies:** If the `pyproject.toml` file is updated with new dependencies, sync the environment:
    ```bash
    uv pip sync pyproject.toml
    ```

-   **Add a New Dependency:**
    ```bash
    # Add a runtime dependency
    uv pip install <package-name>

    # Add a development dependency
    uv pip install <package-name> --group dev
    ```

-   **Run Tests:**
    With the virtual environment active, you can run the test suite using `pytest`:
    ```bash
    pytest
    ```
