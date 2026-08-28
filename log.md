# Dev Log

### 26.08

- Create docs/08-local-vs-prod-architecture.md for architecture recap
- Fix local access to GCS in report route
- Refactor api tree and standardize engines class files
- Create Docker file for discovery job
- Test local and deployed discovery with success
- Move on with phase 3 of the implementation: DAG through worker_routes.py, orchestrator_engine.py (for building DAG from report), execution_engine.py and the use of a Token Bucket.
- Provision cloud tasks for each object category
- Create docs/09-method-overview.md for sequential process overview

### 28.08

- Refactor routes: create Pydantic models for responses, move business logic into dedicated files

TODO:
- Finish reviewing docs/09-method-overview.md
- Test migration phase
- Add cancel job button in UI for pending jobs
- Add estimated discovery time in UI
- Add static info section in report containing concise version of the migration capabilit matrix
- Implement pydantic BaseSettings for env vars