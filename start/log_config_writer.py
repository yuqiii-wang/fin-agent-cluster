"""Write uvicorn ``--log-config`` JSON to a temp file."""
import json
import os
import tempfile


def write_log_config(log_config: dict) -> str:
    """Write *log_config* dict to a temp JSON file for uvicorn ``--log-config``.

    Returns:
        Absolute path to the written temp file.
    """
    fd, path = tempfile.mkstemp(suffix=".json", prefix="uvicorn_log_")
    with os.fdopen(fd, "w") as f:
        json.dump(log_config, f)
    return path
