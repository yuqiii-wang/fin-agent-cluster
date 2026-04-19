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

### Skill Checkup

The e2e-flow skill covers the end-to-end request/response pipeline, you can reference it to understand the architecture and conventions of the project. If you observe any diffs from the e2e-flow skill, update the skill with the new code and logic.
For diagram, draw mermaid.
