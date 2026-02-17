# Excel DID Generator Example

A simple example demonstrating integration with DIDSvc:

- **Single Python/FastAPI server** serves both the frontend and API
- **Frontend**: Static HTML page with Vue.js (via CDN) - no build step required
- **Backend**: Generates Excel files, calculates hashes, and registers artefacts with DIDSvc

This example shows how a real application should interact with DIDSvc - the backend is responsible for communicating with DIDSvc using proper credentials, while the frontend only communicates with its own backend.

## Architecture

```
┌────────────────────────────────────┐     ┌─────────────┐
│     Example Backend (FastAPI)      │────▶│   DIDSvc    │
│            :3001                   │     │   (:8000)   │
│                                    │◀────│             │
│  GET /          → Frontend HTML    │     └─────────────┘
│  POST /generate-report → Excel+DID │
└────────────────────────────────────┘
```

## Prerequisites

- Python 3.11+
- DIDSvc running at http://localhost:8000

## Install and Run

### 1. Start DIDSvc (main backend)

From the project root:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Start the Example

```bash
cd examples/excel_report

# Create virtual environment (first time only)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload --port 3001
```

Open http://localhost:3001 in your browser.

## How It Works

1. User opens http://localhost:3001 and sees the Vue.js frontend
2. User clicks "Generate Excel Sheet"
3. Frontend sends `POST /generate-report` to the backend
4. Backend:
   - Generates sample Excel data
   - Creates the Excel file using openpyxl
   - Calculates SHA-256 multihash (base58btc encoded)
   - Calls DIDSvc (`POST /advisory/record_report`) to register the artefact
   - Returns the Excel file with DID info in response headers
5. Frontend displays the DID and provides a download link for the Excel file

## Configuration

Edit `backend/main.py` to configure:

- `DIDSVC_BASE_URL`: URL of the DIDSvc service (default: `http://localhost:8000`)
- `DIDSVC_API_TOKEN`: API token for authenticating with DIDSvc

## File Structure

```
examples/frontend_excel/
├── README.md
└── backend/
    ├── main.py           # FastAPI server
    ├── requirements.txt  # Python dependencies
    └── static/
        └── index.html    # Vue.js frontend (no build required)
