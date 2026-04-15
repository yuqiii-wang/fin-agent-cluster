---
name: project-agent
description: Fin tech quant trading for a langgraph + fastapi project.
argument-hint: Describe the expected argument for this agent, if any.
tools: [vscode, execute, read, agent, edit, search, web, browser, todo]
---

This is a langgraph + fastapi project for fin tech quant trading.

## Biz requirements:

When proposing a new feature, first check if the biz logic makes sense and is feasible.
The biz logic is about quant trading.
Check in fin quant trading domain for best practices and existing solutions before proposing a new feature.

## Dev Requirements:

### Backend:

* Must use `pydantic` models for all data validation and serialization.
* Must use type hints for all functions and methods.
* Must include `docstrings` for all functions and methods.
* Separate code into modules and packages based on functionality, do not create monolithic files.
* For new features, make sure architecture is modular and extensible, add new dir/modules as needed.
* Delete backward compatibility code and dependencies if they are no longer needed.
* Delete old code and files if they are no longer needed, do not keep dead code.
* In there are bulk static config or dict maps, write into sql then on backend start read from sql, do not hard code in the backend code.
* Do not hardcode any API response, do not hardcode any dicts/maps, but to traverse project to see/import class definitions and usages to generate response.

About agent nodes:

* every node has `models` and `tasks` dir.

About DB and SQL:

* Do NOT need to ALTER TABLE nor migration, but just implement new tables and fields, and remove old tables and fields if they are no longer needed, do not keep dead code.

### Frontend:

* For frontend development, use React with TypeScript.
* For backend development, use FastAPI + langChain/LangGraph with Python.
* Try to use existing libraries and tools to accomplish tasks, rather than building from scratch.
* Favor small code change in brevity over large code changes.
* Use `antd` CLI for all antd related queries and operations, do not search antd APIs from memory or the web.
* Do NOT hardcode any UI element in the frontend, all UI elements should be generated from backend APIs, including but not limited to: form fields, buttons, dropdown options, etc.

### Start Guide

* run `start.sh` to start the FastAPI server, which will also start the langgraph agent.

```py
#!/bin/bash
set -e

# Check for .env file
if [ ! -f .env ]; then
  echo "Error: .env file not found"
  exit 1
fi

# Start the FastAPI server
python run.py
```

Test Guide

* run `test_appl.py` to complete e2e test to make sure the flow can work.

Agent Node Guide

