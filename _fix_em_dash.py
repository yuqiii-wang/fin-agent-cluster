"""Replace U+2014 em-dash with '--' in all modified .py files."""
import pathlib
import sys

TARGET_FILES = [
    "backend/resources/stats/models.py",
    "backend/resources/stats/client.py",
    "backend/resources/stats/__init__.py",
    "backend/resources/stats/routing.py",
    "backend/resources/stats/providers/errors/__init__.py",
    "backend/resources/stats/providers/errors/codes.py",
    "backend/resources/stats/providers/akshare/__init__.py",
    "backend/resources/stats/providers/akshare/fetcher.py",
    "backend/resources/stats/providers/akshare/transformer.py",
    "backend/resources/stats/providers/fmp/__init__.py",
    "backend/resources/stats/providers/fmp/fetcher.py",
    "backend/resources/stats/providers/fmp/fundamentals_fetcher.py",
    "backend/resources/stats/providers/fmp/transformer.py",
    "backend/resources/stats/providers/yfinance/__init__.py",
    "backend/resources/stats/providers/yfinance/fetcher.py",
    "backend/resources/stats/providers/yfinance/fundamentals_fetcher.py",
    "backend/resources/stats/providers/yfinance/transformer.py",
    "backend/resources/stats/providers/mock/__init__.py",
    "backend/resources/stats/providers/mock/stats.py",
    "backend/resources/stats/providers/mock/transport.py",
    "backend/langgraph/models/common_tasks/task_seqs/get_and_calculate_stats/models.py",
    "backend/langgraph/models/common_tasks/task_seqs/get_and_calculate_stats/get_stats.py",
    "backend/langgraph/models/common_tasks/task_seqs/get_and_calculate_stats/seq.py",
    "backend/langgraph/models/common_tasks/task_seqs/get_and_calculate_stats/calculate_stats.py",
    "backend/langgraph/models/common_tasks/task_seqs/get_and_calculate_stats/calculation_utils/calculate_ohlcv_stats.py",
    "backend/langgraph/models/common_tasks/task_seqs/get_and_calculate_stats/calculation_utils/calculation_options_utils/models.py",
    "backend/langgraph/models/common_tasks/task_seqs/get_and_calculate_stats/calculation_utils/calculation_options_utils/calculate_option_stats.py",
    "backend/langgraph/nodes/prepare_options/node.py",
    "backend/langgraph/nodes/prepare_options/models/output.py",
    "backend/langgraph/nodes/prepare_futures/node.py",
    "backend/langgraph/nodes/prepare_derivatives/agent_steps/calculate_options.py",
    "backend/langgraph/nodes/prepare_derivatives/agent_steps/study_web.py",
    "backend/langgraph/nodes/prepare_derivatives/agent_steps/extraction_schema.py",
    "backend/langgraph/models/common_tasks/task_seqs/prepare_fundamentals/get_fundamentals.py",
]

EM_DASH = "\u2014"  # —
REPLACEMENT = "--"

total_replaced = 0
for rel_path in TARGET_FILES:
    p = pathlib.Path(rel_path)
    if not p.exists():
        continue
    content = p.read_text(encoding="utf-8")
    count = content.count(EM_DASH)
    if count:
        new_content = content.replace(EM_DASH, REPLACEMENT)
        p.write_text(new_content, encoding="utf-8")
        total_replaced += count
        print(f"  fixed {p}  ({count} replacements)")

print(f"\nTotal em-dashes replaced: {total_replaced}")
sys.exit(0)
