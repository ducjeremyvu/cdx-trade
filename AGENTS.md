# Repository Guidelines

## Project Structure & Module Organization
- `main.py` contains the current executable entry point and demo logic.
- `pyproject.toml` defines project metadata and dependencies.
- `uv.lock` pins resolved dependency versions for `uv`.
- `README.md` is present but currently empty.

## Build, Test, and Development Commands
- `python main.py`: run the application directly.
- `python -m main`: alternate way to run the entry point.
- `uv sync`: install dependencies using `uv` (recommended when using `uv.lock`).
- `uv run python main.py`: run within the `uv` environment.

## Coding Style & Naming Conventions
- Use 4-space indentation and PEP 8 formatting.
- Prefer `snake_case` for functions/variables and `PascalCase` for classes.
- Keep modules small and focused; add new modules alongside `main.py` as they grow.
- No formatter or linter is configured yet; add one if needed (e.g., `ruff`, `black`).

## Testing Guidelines
- No tests are currently defined.
- If adding tests, use a `tests/` directory and name files `test_*.py`.
- Consider `pytest` as the default framework (add it to `pyproject.toml`).

## Commit & Pull Request Guidelines
- No commit history exists yet, so no established commit message convention.
- Suggested format: `type: short summary` (e.g., `feat: add alpaca client`).
- PRs should include a clear description, testing notes, and any relevant screenshots/logs.

## Configuration & Secrets
- Do not commit API keys or credentials.
- Use environment variables for runtime configuration (e.g., `ALPACA_API_KEY`).
