"""Lance l'application : `python -m runai.app` puis http://127.0.0.1:8000."""

import os

import uvicorn

from runai.app.server import create_app

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.getenv("RUNAI_APP_HOST", "127.0.0.1"),
        port=int(os.getenv("RUNAI_APP_PORT", "8000")),
    )
