import logging
import os
import sqlite3
from datetime import datetime

from flask import Flask, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

# configure logging early so optional-import warnings appear properly
logging.basicConfig(level=logging.DEBUG)

# Optional third-party libraries (not strictly required for basic app routes).
try:
    import qrcode
except ImportError:  # module not available
    qrcode = None
    logging.warning("Optional package 'qrcode' not installed; QR features disabled.")

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None
    logging.warning("Optional package 'Pillow' not installed; image features disabled.")

try:
    import reportlab
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
except ImportError:
    reportlab = None
    letter = None
    canvas = None
    inch = None
    ImageReader = None
    logging.warning(
        "Optional package 'reportlab' not installed; PDF features disabled."
    )

# Application and DB setup
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# Allow overriding database via env var (PythonAnywhere convenience)
DATABASE = os.environ.get("DATABASE", os.path.join(APP_DIR, "torino.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key")


def _ensure_db_path():
    """Ensure the directory for DATABASE exists and is writable."""
    d = os.path.dirname(DATABASE)
    if d and not os.path.exists(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            logging.exception(f"Unable to create DB directory: {d}")


_ensure_db_path()


def get_db_connection():
    """Return a sqlite3 connection with row factory set."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create necessary tables if they don't exist."""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                """
            CREATE TABLE IF NOT EXISTS tiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT,
                supplier TEXT NOT NULL,
                sqft_per_box REAL NOT NULL,
                style TEXT NOT NULL,
                size TEXT NOT NULL,
                torino_code TEXT UNIQUE NOT NULL,
                quantity INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                image TEXT,
                color_group TEXT DEFAULT 'White'
            )
            """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_torino_code ON tiles (torino_code)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_color_group ON tiles (color_group)"
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_quantity ON tiles (quantity)")
            c.execute(
                """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT,
                phone TEXT,
                email TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
            )
            c.execute(
                """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                torino_code TEXT NOT NULL,
                client_id INTEGER,
                client_name TEXT,
                address TEXT,
                sq_ft REAL,
                install_date TEXT,
                installer_fee REAL,
                budget REAL,
                schedule TEXT,
                status TEXT DEFAULT 'Scheduled',
                photo_url TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (torino_code) REFERENCES tiles (torino_code),
                FOREIGN KEY (client_id) REFERENCES clients (id)
            )
            """
            )
            c.execute(
                """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL
            )
            """
            )
            # ensure an admin user exists
            c.execute(
                "INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)",
                ("admin", generate_password_hash("password")),
            )
            conn.commit()
            # seed a sample tile if none exist so the showroom is not empty
            c.execute("SELECT COUNT(1) as cnt FROM tiles")
            row = c.fetchone()
            if row and row[0] == 0:
                c.execute(
                    (
                        "INSERT INTO tiles (name, price, description, supplier, "
                        "sqft_per_box, style, size, torino_code, quantity, "
                        "created_at, image, color_group) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    (
                        "Sample Tile",
                        1.0,
                        "Sample tile for demo",
                        "DemoSupplier",
                        10.0,
                        "SampleStyle",
                        "12x12",
                        "SAMPLE-001",
                        100,
                        datetime.now().isoformat(),
                        None,
                        "White",
                    ),
                )
                conn.commit()
    except sqlite3.Error as e:
        logging.error(f"DB init error: {e}")
        raise


def get_user(username: str):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT password FROM users WHERE username=?", (username,))
            row = c.fetchone()
            return row["password"] if row else None
    except sqlite3.Error as e:
        logging.error(f"DB get_user error: {e}")
        return None


def add_user(username: str, password: str):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            hashed = generate_password_hash(password)
            c.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, hashed),
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False
    except sqlite3.Error as e:
        logging.error(f"DB add_user error: {e}")
        return False


def get_tiles(page=1, per_page=20, color_group=None):
    try:
        params = []
        query = "SELECT * FROM tiles"
        if color_group:
            query += " WHERE color_group = ?"
            params.append(color_group)
        query += " LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(query, tuple(params))
            rows = c.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logging.error(f"DB get_tiles error: {e}")
        return []


def get_tile_by_code(code: str):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM tiles WHERE torino_code = ?", (code,))
            row = c.fetchone()
            return dict(row) if row else None
    except sqlite3.Error as e:
        logging.error(f"DB get_tile_by_code error: {e}")
        return None


def add_client(name: str, address: str, phone: str, email: str):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO clients (name, address, phone, email, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, address, phone, email, "", datetime.now().isoformat()),
            )
            conn.commit()
            return c.lastrowid
    except sqlite3.Error as e:
        logging.error(f"DB add_client error: {e}")
        return None


def add_project(
    torino_code,
    client_name,
    address,
    sq_ft,
    install_date,
    installer_fee=0.0,
    notes="",
    client_id=None,
    budget=None,
    schedule=None,
):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            # ensure tile exists
            c.execute("SELECT * FROM tiles WHERE torino_code = ?", (torino_code,))
            tile = c.fetchone()
            if not tile:
                logging.error("Tile not found for add_project")
                return None
            created_at = datetime.now().isoformat()
            c.execute(
                (
                    "INSERT INTO projects (torino_code, client_id, client_name, "
                    "address, sq_ft, install_date, installer_fee, budget, "
                    "schedule, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    torino_code,
                    client_id,
                    client_name,
                    address,
                    sq_ft,
                    install_date,
                    installer_fee,
                    budget,
                    schedule,
                    notes,
                    created_at,
                ),
            )
            proj_id = c.lastrowid
            # reduce quantity by boxes used (approx)
            try:
                boxes = float(sq_ft) / float(tile["sqft_per_box"])
            except Exception:
                boxes = 0
            c.execute(
                "UPDATE tiles SET quantity = quantity - ? WHERE torino_code = ?",
                (boxes, torino_code),
            )
            conn.commit()
            return proj_id
    except sqlite3.Error as e:
        logging.error(f"DB add_project error: {e}")
        return None


def get_project_by_id(project_id):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
            row = c.fetchone()
            return dict(row) if row else None
    except sqlite3.Error as e:
        logging.error(f"DB get_project_by_id error: {e}")
        return None


init_db()
# The following block was previously malformed (unbalanced try/except and incorrect
# indentation). Kept below as reference but actual DB helper implementations are
# provided above and used by the routes.
# (stray brace removed)

# SUPPLIERS = {
#     'Ames': 'Agri', 'Ceratec': 'Sienna', 'C&S': 'Capri', 'Daltile': 'Vetro',
#     'Midgley West': 'Milano', 'Olympia': 'Orzo', 'Julian': 'Roma', 'Sarana': 'Sassa'
# }
# @app.errorhandler(Exception)
# def handle_error(e):
#     logging.error(f"Error: {str(e)}")
#     return "An error occurred. Please try again.", 500

# (Long commented-out reference code omitted for brevity)


@app.route("/")
def showroom():
    # Simple showroom: list first page of tiles
    tiles = get_tiles(page=1, per_page=9, color_group="White")
    html = "<h1>Torino Tile - Showroom</h1>"
    for t in tiles:
        html += f"<div><strong>{t.get('name')}</strong> - {t.get('torino_code')}</div>"
    return html


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        stored_hash = get_user(username)
        if stored_hash and check_password_hash(stored_hash, password):
            session["user"] = username
            return redirect(url_for("showroom"))
        return "Invalid credentials.", 401
    return """
<form method="post">
  <input name="username" placeholder="username">
  <input name="password" type="password" placeholder="password">
  <button type="submit">Login</button>
</form>
"""


if __name__ == "__main__":
    # Only run the development server when executed directly
    app.run(debug=True)
