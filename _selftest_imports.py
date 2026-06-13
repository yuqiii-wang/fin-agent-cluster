"""Self-test: verify all modified modules import cleanly."""
import importlib
import sys

modules = [
    # Top-level stats package
    "backend.resources.stats",
    # providers sub-package
    "backend.resources.stats.providers.errors",
    "backend.resources.stats.providers.errors.codes",
    "backend.resources.stats.providers.akshare",
    "backend.resources.stats.providers.akshare.fetcher",
    "backend.resources.stats.providers.akshare.transformer",
    "backend.resources.stats.providers.fmp",
    "backend.resources.stats.providers.fmp.fetcher",
    "backend.resources.stats.providers.fmp.fundamentals_fetcher",
    "backend.resources.stats.providers.fmp.transformer",
    "backend.resources.stats.providers.yfinance",
    "backend.resources.stats.providers.yfinance.fetcher",
    "backend.resources.stats.providers.yfinance.fundamentals_fetcher",
    "backend.resources.stats.providers.yfinance.transformer",
    "backend.resources.stats.providers.mock",
    "backend.resources.stats.providers.mock.transport",
    # stats client (uses all providers)
    "backend.resources.stats.client",
    "backend.resources.stats.routing",
    "backend.resources.stats.models",
    # Other packages that import from stats (data_type / pipeline refactor)
    "backend.quant.stats",
    "backend.quant.stats.constants",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.models",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_ohlcv_stats",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculation_options_utils.models",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculation_options_utils.handler",
    "backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculation_options_utils.task",
    "backend.langgraph.nodes.prepare_options.node",
    "backend.langgraph.nodes.prepare_options.models.output",
    "backend.langgraph.nodes.prepare_futures.node",
    "backend.langgraph.nodes.prepare_derivatives.agent_steps.calculate_options",
    "backend.langgraph.nodes.prepare_derivatives.agent_steps.study_web",
    "backend.langgraph.nodes.prepare_derivatives.agent_steps.extraction_schema",
]

errors = 0
for name in modules:
    try:
        importlib.import_module(name)
        print(f"  OK   {name}")
    except Exception as exc:
        errors += 1
        print(f"  FAIL {name}: {exc}")

print(f"\nTotal: {len(modules)} modules, {len(modules) - errors} OK, {errors} FAIL")
sys.exit(0 if errors == 0 else 1)
