from fastapi import APIRouter, Request, responses
from fastapi.responses import HTMLResponse

app = APIRouter(tags=["Health"])

@app.get("/", include_in_schema=False)
async def index(request : Request):
  """Router to direct / (index) to /docs in dev/staging environments."""
  return responses.RedirectResponse("/docs")

@app.get("/docs", include_in_schema=False)
async def api_documentation(request: Request):
    return HTMLResponse("""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>DIDSvc API Reference</title>

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


api_summary = ("A service for registering Digital Artefacts as DIDs and "
  "generating Verifiable Crentials for various attestations.")

api_decription = """
# Overview

DIDSvc is a service for registering Digital Artefacts and generating W3C DIDs
(Decentralized Identifiers) VCs (Verifiable Credentials) and VPs (Verifiable
Presentations) for them.

The API is split among various **divisions**: each division corresponds to an
AMD org, project or subsystem, which manages the objects created under their
control.

# References

## AMD-Internal

[DID and VC Mental Model](https://amdcloud.sharepoint.com/:p:/r/sites/ClintsOrg/Shared%20Documents/EYPC%20Analytics/DID%20Items/Presentations/2026-01-DID%20and%20VC%20Mental%20Model.pptx?d=wa39c70ca131842f19201da7132855559&csf=1&web=1&e=sHnVh6) - Short deck with a reference mental model for DAs, DIDs and VCs.

[Tracking of Digital Artefacts](https://amdcloud.sharepoint.com/:p:/r/sites/ClintsOrg/Shared%20Documents/EYPC%20Analytics/DID%20Items/Presentations/2026-01-intro-dids.pptx?d=wc8b9f8e8b4f94606aca4f6a87310ef7f&csf=1&web=1&e=5INmnM) - High level overview of how DIDs may be used for tracking and attesting to the integrity of DAs.

[DIDSvc Project Handbook](https://amdcloud.sharepoint.com/:o:/r/sites/ClintsOrg/Shared%20Documents/EYPC%20Analytics/DID%20Items/DIDSVC%20-%20Project%20Handbook%20-%202026?d=w660bb16803114c4b9e485d0e4babc3bb&csf=1&web=1&e=PyLslS) - Project handbook with various design considerations.


## Authoritative

[W3C DID Specification](https://www.w3.org/TR/did-1.0)

[W3C VC Specification](https://www.w3.org/TR/vc-data-model/)

"""
