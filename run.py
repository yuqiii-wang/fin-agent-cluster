"""Run the FastAPI server with proper Windows asyncio configuration."""
import asyncio
import selectors
import sys
import uvicorn
from app.config import get_settings


async def _serve(config: uvicorn.Config) -> None:
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
    )

    if sys.platform == "win32":
        # psycopg (and psycopg2) require SelectornewsLoop; Windows defaults to ProactornewsLoop
        loop_factory = lambda: asyncio.SelectornewsLoop(selectors.SelectSelector())
        asyncio.run(_serve(config), loop_factory=loop_factory)
    else:
        asyncio.run(_serve(config))
