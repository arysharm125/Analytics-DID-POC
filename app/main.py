from fastapi import FastAPI, Request
import logging
from fastapi.responses import HTMLResponse
from app.services.vault import vault_is_authenticated

# ==========================
# Logging
# ==========================
logging.config.fileConfig("deployment/logging.ini", disable_existing_loggers=False)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger = logging.getLogger("deployment")


# ==========================
# FastAPI App
# ==========================
app = FastAPI(docs_url=None, redoc_url=None)

# ==========================
# Register Routers
# ==========================
from app.routers.policy import router as policy_router
from app.routers.audit import router as audit_router
from app.routers.access import app as access_gateway_app
from app.routers.didrouter import app as did_router, startup_did_router
from app.routers.advisoryrouter import router as advisory_router

app.include_router(policy_router)
app.include_router(audit_router)
app.include_router(did_router)
app.include_router(advisory_router)
app.mount("/access", access_gateway_app)

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

import logging.config

@app.on_event("startup")
async def startup():
    await startup_did_router()


# -------------------------
# Health
# -------------------------
@app.get("/health", tags=["health"])
def health():
    try:
        vault_ok = vault_is_authenticated()
    except Exception:
        vault_ok = False
    return {"status": "ok", "vault_authenticated": vault_ok}

# EOF

