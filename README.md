# Monday.com Account Migration Assessment Tool

This tool performs a read-only discovery of a Monday.com account and generates a comprehensive Markdown report summarizing the objects discovered (Workspaces, Boards, Groups, Columns, Items) and their readiness for automated migration.

## Setup

This project uses [`uv`](https://github.com/astral-sh/uv) for fast Python dependency and environment management.

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Set your API Key:**
   You must provide a valid Monday.com API token via an environment variable.
   ```bash
   export MONDAY_API_KEY="your_personal_or_app_api_token"
   ```

## Usage

### 1. Full Discovery & Reporting
To hit the Monday.com API, download the entire account structure, and generate the report:

```bash
uv run python main.py
```
*This will output two files:*
- `local_inventory.json`: The raw JSON dump of the discovered account structure.
- `pre_migration_report.md`: The human-readable Markdown report.

### 2. Skip Discovery (Use Cache)
If you have already run a full discovery and just want to tweak the classification rules or test changes to the Markdown report formatting, use the `--use-cache` flag. This skips all API calls and parses your existing `local_inventory.json`.

```bash
uv run python main.py --use-cache
```

## Development & Testing
To run the offline test suite and enforce formatting:
```bash
uv run pytest tests/
uv run ruff check --fix .
uv run ruff format .
```
