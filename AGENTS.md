
# Agents

This document outlines best practices and instructions for coding agents interacting with the gantry project.

## `uv` Virtual Environment

To initialize the virtual environment for running commands (like `pytest`), use the following:

```
source .venv/bin/activate
```


## Testing

To run the test suite, use the following command:

```bash
uv run --no-cache pytest -m "not slow"
```

The `--no-cache` flag avoids cache permission issues, and the `-m` option skips the slow tests which is OK in most cases.

Alternatively, you can activate the virtual environment directly:

```bash
source .venv/bin/activate
pytest -m "not slow"
```
