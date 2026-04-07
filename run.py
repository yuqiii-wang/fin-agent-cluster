"""Run the FastAPI server with proper Windows asyncio configuration."""
import asyncio
import logging
import selectors
import sys
import uvicorn
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


async def _serve(config: uvicorn.Config) -> None:
    """Start the uvicorn server."""
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    settings = get_settings()
    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=settings.FASTAPI_PORT,
        reload=False,
        workers=1,
        log_level="info",
    )

    if sys.platform == "win32":
        # psycopg requires SelectorEventLoop; Windows defaults to ProactorEventLoop
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.run(_serve(config), loop_factory=loop_factory)
    else:
        asyncio.run(_serve(config))
