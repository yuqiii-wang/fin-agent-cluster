---
name: project-agent
description: Fin tech quant trading for a langgraph + fastapi project.
argument-hint: Describe the expected argument for this agent, if any.
tools: [vscode, execute, read, agent, edit, search, web, browser, todo]
---

This is a langgraph + fastapi project for fin tech quant trading.

## Biz requirements

When proposing a new feature, first check if the biz logic makes sense and is feasible.
The biz logic is about quant trading.
Check in fin quant trading domain for best practices and existing solutions before proposing a new feature.

## Dev Requirements

* Do NOT add hardcoded time lag or grace period for any flow; if got racing or other safety concerns, implement proper locking or queuing mechanism to ensure safety without hardcoded time lag.
* Debug on git bash, although backend runs on WSL2, only try wsl if want to `python run.py` to launch the whole backend, for other debugging purposes, use git bash to run individual files or commands, do not use wsl for debugging.
* Most of the infra, e.g., KONG API, Redis, Postgres, Centrifugo, Grafana stack are run in docker.

### Backend and Frontend Communications

* There are two main flows: streaming flow with celery + redis streams, and non-streaming flow with request/response or SSE; do NOT mix the two flows, implement new features in one flow or the other based on the nature of the feature, but do not mix both flows in the same feature.
* main fast-api gathers celery worker results and pg notifies client application via SSE; do not send notifications directly from celery workers, but always go through main fast-api to send notifications to client application, to ensure all notifications are sent in a consistent manner and to avoid racing conditions or missed notifications.
* In every large component, need to mkdir a sub-dir called `errors` to store error code and description capturing likely exceptions or racing or any thing suspected. The error codes will be used in logs and return to UI to help locate error. And in migration or code cleanup, or if some error code is no longer used, just delete/migrate it, do not keep dead code.

### Backend

* Must use `pydantic` models for all data validation and serialization.
* Must use type hints for all functions and methods.
* For every new module/package/dir, must include a `__init__.py` file to make it a package with `__all__` that makes it easy to import.
* Must include `docstrings` for all functions and methods.
* Separate code into modules and packages based on functionality, do not create monolithic files.
* For new features, make sure architecture is modular and extensible, add new dir/modules as needed.
* Delete backward compatibility code and dependencies if they are no longer needed.
* Delete old code and files if they are no longer needed, do not keep dead code.
* You are an excellent architect always checking if new code should sit in the current file or if a new file/dir should be created, or existing modules/packages should be semantically speaking more suitable to host new code.
* In there are bulk static config or dict maps, write into sql then on backend start read from sql, do not hard code in the backend code.
* Do not hardcode any API response, do not hardcode any dicts/maps, but to traverse project to see/import class definitions and usages to generate response.
* streaming related flow be with redis streams with celery; others are with SSE or request/response.
* Backend runs on WSL2 so it is `--pool=prefork` to celery, but test can just run `--pool=solo` on windows git bash.

About agent nodes:

* every node has `models` and `tasks` dir.

About DB and SQL:

* Do NOT need to ALTER TABLE nor migration, but just implement new tables and fields, and remove old tables and fields if they are no longer needed, do not keep dead code.

### Frontend

* For frontend development, use React with TypeScript.
* For backend development, use FastAPI + langChain/LangGraph with Python.
* Try to use existing libraries and tools to accomplish tasks, rather than building from scratch.
* Favor small code change in brevity over large code changes.
* Use `antd` CLI for all antd related queries and operations, do not search antd APIs from memory or the web.
* Do NOT hardcode any UI element in the frontend, all UI elements should be generated from backend APIs, including but not limited to: form fields, buttons, dropdown options, etc.
* `cd frontend && npm run dev` to start frontend to launch browser to debug UI.

### Skill Checkup

The e2e-flow skill covers the end-to-end request/response pipeline, you can reference it to understand the architecture and conventions of the project. If you observe any diffs from the e2e-flow skill, update the skill with the new code and logic.
For diagram, draw mermaid.

### Debug

* logs are in backend/logs, check logs for debugging and understanding the flow of the project.
* Ignore timeout or cancel since they are triggered by requested timeout or manual cancel
