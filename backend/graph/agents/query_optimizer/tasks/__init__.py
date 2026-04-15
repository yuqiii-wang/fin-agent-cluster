"""Tasks sub-package for the query_optimizer node.

Each module implements one sequential step of the query_optimizer pipeline:

- :mod:`comprehend_basics`    — Task 1: stream structured JSON from the LLM
- :mod:`validate_basics`      — Task 2: correct region / index / industry against SQL static data
- :mod:`populate_json`        — Task 3: validate basics and build full output using static templates
- :mod:`populate_sec_profile` — Task 4: ensure sec_profiles row exists for the resolved ticker
"""

from backend.graph.agents.query_optimizer.tasks.comprehend_basics import comprehend_basics
from backend.graph.agents.query_optimizer.tasks.validate_basics import validate_basics
from backend.graph.agents.query_optimizer.tasks.populate_json import populate_json
from backend.graph.agents.query_optimizer.tasks.populate_sec_profile import populate_sec_profile

__all__ = ["comprehend_basics", "validate_basics", "populate_json", "populate_sec_profile"]
