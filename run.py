"""Entry point — delegates to :mod:`start.app_runner`."""
import argparse
import sys

from start.app_runner import start_app


def main() -> int:
    """Parse CLI args and start the server."""
    parser = argparse.ArgumentParser(description="Run the FastAPI server.")
    parser.add_argument("--no-proxy", action="store_true", help="Disable the use of the proxy even if configured.")
    args = parser.parse_args()
    return start_app(no_proxy=args.no_proxy)


if __name__ == "__main__":
    sys.exit(main())
