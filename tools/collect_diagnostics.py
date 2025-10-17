"""Collect environment and app diagnostics for PythonAnywhere deployment.

Run this on the server (PythonAnywhere) in your project's source directory. It writes a timestamped
log file into the `logs/` folder with information useful for debugging import-time and WSGI errors.

Usage (example):
  python tools/collect_diagnostics.py --wsgi /var/www/yourusername_pythonanywhere_com_wsgi.py \
      --error-log /var/log/apache2/error.log

If you don't pass paths, the script will probe common locations and include whatever it can.
"""

from __future__ import annotations
import argparse
import datetime
import hashlib
import os
import platform
import subprocess
import sys
import traceback

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")


def safe_run(cmd, cwd=None):
    try:
        p = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            text=True,
            timeout=30,
        )
        return p.returncode, p.stdout
    except Exception as e:
        return 1, f"Exception running {cmd}: {e}\n"


def collect(argv: list[str]) -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wsgi", help="Path to WSGI file to dump (optional)")
    parser.add_argument("--error-log", help="Path to web error log to tail (optional)")
    parser.add_argument(
        "--max-log-lines", type=int, default=200, help="Lines to tail from error log"
    )
    args = parser.parse_args(argv)

    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(LOG_DIR, f"diagnostics-{ts}.txt")

    with open(out_path, "w", encoding="utf-8") as out:

        def writeline(h, v=""):
            out.write(f"--- {h} ---\n")
            out.write(str(v) + "\n\n")

        # Basic environment
        writeline("Timestamp (UTC)", ts)
        writeline("Platform", platform.platform())
        writeline("Python version", sys.version.replace("\n", " "))
        writeline("Python executable", sys.executable)
        writeline("CWD", os.getcwd())

        # app.py fingerprint
        app_file = os.path.join(os.getcwd(), "app.py")
        if os.path.exists(app_file):
            try:
                count = sum(1 for _ in open(app_file, encoding="utf-8"))
                sha = hashlib.sha256(open(app_file, "rb").read()).hexdigest()
                writeline("app.py path", app_file)
                writeline("app.py lines", count)
                writeline("app.py sha256", sha)
            except Exception:
                writeline("app.py read error", traceback.format_exc())
        else:
            writeline("app.py", "NOT FOUND in cwd")

        # Git info if available
        if os.path.isdir(".git"):
            rc, outp = safe_run("git rev-parse HEAD")
            writeline("git rev-parse HEAD (rc)", f"{rc}\n{outp}")
            rc, outp = safe_run("git remote -v")
            writeline("git remote -v (rc)", f"{rc}\n{outp}")
            rc, outp = safe_run("git status --porcelain")
            writeline("git status --porcelain (rc)", f"{rc}\n{outp}")
            rc, outp = safe_run("git log -n 10 --oneline")
            writeline("git log -n 10 --oneline (rc)", f"{rc}\n{outp}")
        else:
            writeline("git", "no .git directory found")

        # Try importing app to capture import-time errors/tracebacks
        writeline("Attempting to import app module (import-time traceback follows)")
        try:
            # clear any cached module
            if "app" in sys.modules:
                del sys.modules["app"]
            import importlib

            app_mod = importlib.import_module("app")
            writeline(
                "Imported app.__file__", getattr(app_mod, "__file__", "<unknown>")
            )
            # Try to find Flask app object
            app_obj = getattr(app_mod, "app", None) or getattr(
                app_mod, "application", None
            )
            writeline("Found app object", repr(app_obj))
        except Exception:
            writeline("Import traceback", traceback.format_exc())

        # Show the WSGI file if provided
        if args.wsgi:
            writeline(f"WSGI file ({args.wsgi}) contents")
            try:
                with open(args.wsgi, "r", encoding="utf-8") as f:
                    writeline("WSGI file head", "\n".join(f.read().splitlines()[:200]))
            except Exception:
                writeline("WSGI read error", traceback.format_exc())

        # Tail the error log if provided or probe common locations
        log_paths = []
        if args.error_log:
            log_paths.append(args.error_log)
        # Common PythonAnywhere log locations (best-effort)
        log_paths.extend(
            [
                "/var/log/apache2/error.log",
                os.path.expanduser("~/error.log"),
                os.path.expanduser("~/www/error.log"),
            ]
        )
        for path in log_paths:
            if not path:
                continue
            path = os.path.expanduser(path)
            if os.path.exists(path):
                writeline(f"Tail of {path}")
                try:
                    rc, outp = safe_run(f"tail -n {args.max_log_lines} {path}")
                    writeline(f"tail {path} (rc={rc})", outp)
                except Exception:
                    writeline(f"tail error for {path}", traceback.format_exc())
            else:
                writeline(f"Log {path}", "NOT FOUND")

        # Show installed packages relevant to the app
        rc, outp = safe_run("python -m pip --version")
        writeline("pip info (rc)", f"{rc}\n{outp}")
        rc, outp = safe_run("python -m pip freeze")
        writeline("pip freeze (rc)", f"{rc}\n{outp}")

        # File permissions in cwd
        try:
            rc, outp = safe_run("ls -la")
            writeline("ls -la (rc)", f"{rc}\n{outp}")
        except Exception:
            writeline("ls error", traceback.format_exc())

    return out_path


if __name__ == "__main__":
    out = collect(sys.argv[1:])
    print("Diagnostics written to:", out)
