import os
import sys

# Ensure project root is importable when running tests directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def run_smoke():
    # Ensure project root is importable when running tests directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    # Import app after adjusting sys.path so module resolution works when run directly
    from app import app

    client = app.test_client()
    r1 = client.get("/")
    print("GET / ->", r1.status_code)
    r2 = client.get("/login")
    print("GET /login ->", r2.status_code)
    # post incorrect creds
    r3 = client.post("/login", data={"username": "bad", "password": "x"})
    print("POST /login (bad creds) ->", r3.status_code)


if __name__ == "__main__":
    run_smoke()
