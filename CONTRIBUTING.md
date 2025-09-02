# Contributing to FinBase - The Open Ledger

Thanks for helping build the open financial data platform. This document covers documentation conventions, how to lint docstrings and types, and how to generate navigable docs.


## Documentation style guide

Use English for all developer-facing documentation. Keep comments concise and useful—explain why, not just what.

- Python (all services)
  - Docstrings follow PEP 257 with a Google-style layout for Args/Returns/Raises.
  - Each public module, class, and function should have a docstring.
  - First line: concise imperative summary ending with a period.
  - Leave a blank line after the summary before details/sections.
  - Example:
    
    """Short summary.
    
    Longer description if needed.
    
    Args:
      foo: Meaning of foo.
    Returns:
      What is returned.
    Raises:
      ValueError: When foo is invalid.
    """

- TypeScript/React (frontend-service)
  - Use TSDoc/JSDoc for exported types, components, hooks, and utilities.
  - Document props and return types. Prefer exact types over any.
  - Keep examples minimal and relevant.
  - Example:
    
    /**
     * Renders a candlestick chart with live updates.
     * @param props.ticker - Symbol to display (e.g. "AAPL").
     * @param props.interval - Aggregation interval.
     */

- SQL (init.sql, migrations)
  - Add a header block describing schema purpose, constraints, and indexes.
  - Inline comments for non-obvious choices and performance notes.

- Shell/PowerShell
  - Use comment-based help blocks (Synopsis, Description, Parameter, Example).

- YAML (docker-compose, k8s)
  - Add top-level context for each service: purpose, dependencies, ports, key env vars.

- Dockerfiles
  - Comment each stage and major instruction; note security choices (non-root user, minimal base image) and exposed ports.


## Linting documentation and types

Run these locally before opening a PR. Commands assume Windows PowerShell; adjust for your shell if needed.

- Python docstrings (pydocstyle)
  1) Install pydocstyle once (user scope):
     python -m pip install --user pydocstyle
  2) Check all Python services:
     python -m pydocstyle services/api-service services/backfill-worker-service services/collector-yfinance services/quality-service services/storage-service
  3) Optional: get only counts (less noise):
     python -m pydocstyle --count services/*-service

- TypeScript type checks (tsc)
  1) Install dependencies (once per clone):
     Push-Location services/frontend-service; npm install --no-audit --progress=false; Pop-Location
  2) Run the compiler (no emit):
     Push-Location services/frontend-service; npx tsc --noEmit -p tsconfig.json; Pop-Location


## Generating navigable documentation

You can generate browsable HTML docs for Python and TypeScript code.

- Python (pdoc)
  - Install pdoc (user scope):
    python -m pip install --user pdoc
  - Generate docs under docs/python/ for core services:
    python -m pdoc --output-dir docs/python services/api-service services/backfill-worker-service services/quality-service services/storage-service
  - Open docs/python/index.html in your browser.

- TypeScript (TypeDoc)
  - A Typedoc config is provided at services/frontend-service/typedoc.json.
  - Generate docs into docs/typedoc:
    Push-Location services/frontend-service; npx typedoc --options typedoc.json; Pop-Location
  - Open docs/typedoc/index.html in your browser.


## Notes and recommendations

- Keep docstrings and comments up to date with behavior changes.
- Prefer small, focused functions: it makes good docs easy and linters happy.
- If you need to suppress a specific pydocstyle rule, prefer fixing the code first; only ignore with a clear justification.
- For frontend types involving third-party libraries (e.g., lightweight-charts), use the library’s exported types (e.g., UTCTimestamp) to satisfy the compiler.

