---
name: project-agent
description: Fin tech quant trading for a langgraph + fastapi project.
argument-hint: Describe the expected argument for this agent, if any.
tools: [vscode, execute, read, agent, edit, search, web, browser, todo]
---

This is a langgraph + fastapi project for fin tech quant trading.

Biz requirements:

When proposing a new feature, first check if the biz logic makes sense and is feasible.
The biz logic is about quant trading.
Check in fin quant trading domain for best practices and existing solutions before proposing a new feature.

Dev Requirements:

* Must use `pydantic` models for all data validation and serialization.
* Must use type hints for all functions and methods.
* Must include docstrings for all functions and methods.
* Separate code into modules and packages based on functionality, do not create monolithic files.

* For frontend development, use React with TypeScript.
* For backend development, use FastAPI + langChain/LangGraph with Python.
* Try to use existing libraries and tools to accomplish tasks, rather than building from scratch.
* Favor small code change in brevity over large code changes.

DB Dev requirements:

* On sql/database changes, do NOT use ALTER TABLE, but just drop old table, add new cols/new tables.
* `*_exts` refer to extensions, which are slow-changing tables
* `*_stats` refer to statistics
* `*_stat_aggregs` refer to aggregated statistics, usually by rolling windows.
