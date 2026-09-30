"""FastAPI instance served by the Vercel Python runtime."""

from dynamis.serving.app import create_app

app = create_app()
