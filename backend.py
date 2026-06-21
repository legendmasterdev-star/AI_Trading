import os

from trading_backend.api import app


def run():
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "6400"))
    uvicorn.run("backend:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
