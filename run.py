"""Run the FastAPI server with proper Windows asyncio configuration."""
import asyncio
import sys
import uvicorn
from app.config import get_settings

if __name__ == "__main__":
    # On Windows, must use SelectorEventLoop for psycopg compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.FASTAPI_PORT,
        reload=False,
        workers=1,  # Single worker avoids event loop issues
    )
