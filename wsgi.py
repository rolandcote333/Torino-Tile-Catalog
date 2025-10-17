from app import app as application  # noqa: F401

"""
PythonAnywhere expects a WSGI callable named `application`.
This file simply exposes the Flask `app` object as `application`.
If you need to set env vars for PythonAnywhere, do so in the web UI.
"""
