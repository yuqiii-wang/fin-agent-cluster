import importlib
import sys

modules = [
    "backend.resources.stats.models",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.models",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.seq",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_ohlcv_stats",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculation_options_utils.models",
    "backend.langgraph.nodes.prepare_options.models.output",
    "backend.langgraph.nodes.prepare_options.node",
    "backend.langgraph.nodes.prepare_futures.node",
]

errors = []
for m in modules:
    try:
        importlib.import_module(m)
        print(f"OK    {m}")
    except Exception as e:
        errors.append((m, str(e)))
        print(f"FAIL  {m}: {e}")

print(f"\nTotal: {len(modules)} modules. Errors: {len(errors)}")
sys.exit(0 if not errors else 1)
