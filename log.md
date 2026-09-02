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

- Refactor routes: create Pydantic models for responses, move business logic into dedicated files, use FastAPI DI for engines
- Study and apply SOLI"D" principle in engines using Protocol and a callable factory
- Add Pydantic models where dicts where used
- Add schemas to docs
- Reviewed docs/09-method-overview.md
- Apply provisioned cloud task to infra
- Study and plan implem of re-enqueue pattern for tasks
- Study and plan implem of local pattern to replace cloud tasks

### 31.08

- Implement re-enqueue system for tasks using token bucket
- Implement local asyncio queue for local task dispatch
- Add dead-letter queue
- Add cancel job and delete all job data button in UI
- Add static info section in report and UI containing concise version of the migration capabilit matrix
- Implement pydantic BaseSettings for env vars, add env vars to docs

### 02.10

- gcp_clients.py : replace clients with async versions when possible, running storage in asyncio.to_thread, refactor with protocol


TODO:
- TEST MIGRATION PHASE
- Fix tests
- Document tests and remove bloat
- Replace local asyncio queue with cloud tasks 
- Move from background tasks locally to container-centered approach reproducing production env architecture
- Add estimated discovery time in UI