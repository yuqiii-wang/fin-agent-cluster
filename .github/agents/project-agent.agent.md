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
* Most of the infra, e.g., nginx-internal, Redis, Postgres, Centrifugo, Grafana stack are run in docker.
* OK to add debug logs for debugging or understanding the flow, ok to keep err logs for error cases, but do NOT add info or debug logs for normal flow.
* If debugging takes a long time, once resolved should add error logs for the issue encountered.
* In docs dir, there is a debugs dir, write debug docs for any non-trivial debugging process.
* In langgraph, horizontally early/before and later/after means within the same version the nodes are position in the close to root node (early/before) or close to leaf nodes (later/after); vertically early/before and later/after means across versions, the earlier version is early/before and the later version is later/after.
* Do NOT use test/mock names if the code is for more generic use.
* Config setup can be found from docker_compose.yml and backend/config.py, do not hardcode any config in the code, but to add in config files and read from config in the code.
* study feasibility and complexity and maintainability, if good then start implementation, if not good, propose your answer , user confirmed then continue implementation.
* For new features new refactor, do NOT keep old code for backward compatibility nor fallback, but to delete old code and just throw err if hit original code path, do not keep dead code.

### Backend and Frontend Communications

* In every large component, need to mkdir a sub-dir called `errors` to store error code and description capturing likely exceptions or racing or any thing suspected. The error codes will be used in logs and return to UI to help locate error. And in migration or code cleanup, or if some error code is no longer used, just delete/migrate it, do not keep dead code.
* Ensure all SSE has ack mechanism that for event notification, UI having received the event will send ack to backend, and backend will send back ack to UI. Backend fast api with the same graph thread id listens for the ack and proceed with the flow.
* Always be careful about racing conditions in the flows, and implement proper locking or queuing mechanism to ensure safety without hardcoded time lag.
* `ui` nginx is used only to host static frontend files, and nginx-internal is used for all API calls from frontend to backend, do not use `ui` nginx for any API calls, but to use nginx-internal for all API calls.
* For HTTP request/response flow, use HTTP2, for bidirectional streaming flow (SSE notification and LLM streaming) between frontend and backend, use centrifugo.

### Backend

* For backend development, use FastAPI + langChain/LangGraph with Python.
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
* SQL write happens on PG DB primary, but read happens on replicas; ensure sql table schemas are consistent across all primary and replicas if updated sql tables.

About agent nodes:

* every node has `models` and `tasks` dir.
* try to use native `langgraph` methods as much as possible, e.g., for `@task`, there is native cache, redis is used to implement cache for `@task`

About DB and SQL:

* Do NOT need to ALTER TABLE nor migration, but just implement new tables and fields, and remove old tables and fields if they are no longer needed, do not keep dead code.

### Frontend

* For frontend development, use React with TypeScript.
* Try to use existing libraries and tools to accomplish tasks, rather than building from scratch.
* Favor small code change in brevity over large code changes.
* Use `"@langchain/react";`
* Use `antd` CLI for all antd related queries and operations, do not search antd APIs from memory or the web.
* Do NOT hardcode any UI element in the frontend, all UI elements should be generated from backend APIs, including but not limited to: form fields, buttons, dropdown options, etc.
* Run playwright test in git bash for debugging.
* Show spinner between UI action and backend SSE ack response.

### Debug

* logs are in backend/logs, check logs for debugging and understanding the flow of the project.
* Test against https 3000 for frontend by playwright.
* For backend, by `/home/yuqi/miniconda3/bin/python /mnt/e/fin-trading-cluster/run.py` to launch the whole backend.
