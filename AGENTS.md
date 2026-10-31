# Developer Context

- This repository contains SimPyTick (import `simpytick`), a Python 3.10+ timer
  and cancellable-sleep package. Source is in `simpytick/`; tests are in `tests/`.
  Preserve process/thread backend behavior, cancellation, and worker cleanup.
- Use uv for Python commands. Run from this repository root; follow the setup
  in `README.md`. Process examples require a `__main__` guard for spawn.
- Validate changes with `uv run python .github/scripts/run_checks.py unit` and
  `uv run python .github/scripts/run_checks.py lint` after installing development
  requirements. Test worker changes with actual spawned processes.
- Keep runtime dependencies in `pyproject.toml` and `requirements.txt` aligned.
  The version source is `simpytick/_version.py`; do not bump it unless requested.
- Read `.github/CI.md` for CI and release policy. The publishing workflow is
  `.github/workflows/pypi_publish.yml`; pushes to `master` publish to PyPI.
  Do not publish, push tags, or commit without explicit authorization.
- Pre-1.0.0 releases are testing versions; semantic versioning starts at 1.0.0.