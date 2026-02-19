from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator
import logging
import logging.config

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.config import get_config
from app.services.did_service import did_service_lifespan
from app.version import VERSION

# ==========================
# Logging
# ==========================
logging.config.fileConfig("deployment/logging.ini", disable_existing_loggers=False)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger = logging.getLogger("deployment")


# ==========================
# FastAPI App
# ==========================

@asynccontextmanager
async def _app_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
  """App lifespan generator. Controls the lifetime of global/singleton objects."""
  async with AsyncExitStack() as stack:
    await startup_did_router()
    await stack.enter_async_context(did_service_lifespan())

    # Add additional lifespans above this point.
    yield


app = FastAPI(docs_url=None, redoc_url=None, lifespan=_app_lifespan, version=VERSION)

# ==========================
# Register Routers
# ==========================
# from app.routers.policy import router as policy_router
from app.routers.epdw import app as did_router, startup_did_router
from app.routers.advisory_router import router as advisory_router
from app.routers.generic_did_router import app as generic_did_router
from app.routers.health import app as health_router

# app.include_router(policy_router)
app.include_router(did_router)
app.include_router(advisory_router)

# Conditionally include generic DID router based on feature flag
if get_config().features.generic_did_router:
  app.include_router(generic_did_router)

app.include_router(health_router)

@app.get("/docs", include_in_schema=False)
async def api_documentation(request: Request):
    return HTMLResponse("""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>Elements in HTML</title>

    <script src="https://unpkg.com/@stoplight/elements/web-components.min.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/@stoplight/elements/styles.min.css">
  </head>
  <body>

    <elements-api
      apiDescriptionUrl="openapi.json"
      router="hash"
    />

  </body>
</html>""")
