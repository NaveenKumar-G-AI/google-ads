"""Run the Phase-9 backend after setting DATABASE_URL and SUPABASE_URL.

Preferred command:
    uvicorn recovery.api.app:create_app_from_env --factory --host 127.0.0.1 --port 8000
"""

from recovery.api.app import create_app_from_env


def app_factory():
    return create_app_from_env()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("examples_phase9_api:app_factory", factory=True, host="127.0.0.1", port=8000)
