from flask import Flask, request, render_template_string, redirect, session, url_for, Response, send_file, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import sqlite3
from datetime import datetime
import os
import logging
import pandas as pd
import re
from io import BytesIO
import qrcode
from PIL import Image, ImageDraw, ImageFont
import reportlab
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import string

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key')
logging.basicConfig(level=logging.DEBUG)

COLORS = {
    'background': '#f8f3f0',
    'light_stone': '#e0ded9',
    'greige': '#c2b8ac',
    'charcoal': '#8a7d6f',
    'accent': '#d4623c',
    'text': '#4a4a4a'
}

SUPPLIERS = {
    'Ames': 'Agri', 'Ceratec': 'Sienna', 'C&S': 'Capri', 'Daltile': 'Vetro',
    'Midgley West': 'Milano', 'Olympia': 'Orzo', 'Julian': 'Roma', 'Sarana': 'Sassa'
}
@app.errorhandler(Exception)
def handle_error(e):
    logging.error(f"Error: {str(e)}")
    return "An error occurred. Please try again.", 500

def init_db():
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS tiles (
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
            )""")
            c.execute('CREATE INDEX IF NOT EXISTS idx_torino_code ON tiles (torino_code)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_color_group ON tiles (color_group)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_quantity ON tiles (quantity)')
            c.execute("""CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT,
                phone TEXT,
                email TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS projects (
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
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL
            )""")
            c.execute("INSERT OR IGNORE INTO users VALUES ('admin', ?)", (generate_password_hash('password'),))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"DB init error: {e}")
        raise

init_db()
init_db()

def get_user(username):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT password FROM users WHERE username=?", (username,))
            row = c.fetchone()
            return row['password'] if row else None
    except sqlite3.Error as e:
        logging.error(f"DB get_user error: {e}")
        return None

def add_user(username, password):
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            hashed = generate_password_hash(password)
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
            conn.commit()
        return True
    except sqlite3.Error as e:
        logging.error(f"DB add_user error: {e}")
              return False

def generate_sticker_pdf(torino_code):
    tile = get_tile_by_code(torino_code)
    if not tile:
        return None
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    label_width = 2.63 * inch
    label_height = 1 * inch
    cols, rows = 3, 4
    for row in range(rows):
        for col in range(cols):
            x = 0.25 * inch + col * label_width
            y = height - 0.5 * inch - row * label_height
            qr = qrcode.QRCode(version=1, box_size=5, border=1)
            qr.add_data(torino_code)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_buffer = BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            qr_pil = Image.open(qr_buffer)
            qr_pil = qr_pil.resize((80, 80))
            qr_pil.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            p.drawImage(qr_buffer, x, y - 0.8 * inch, width=0.8 * inch, height=0.8 * inch)
            p.setFont("Helvetica-Bold", 10)
            p.drawString(x, y - 0.95 * inch, tile['name'][:30])
            p.setFont("Helvetica", 8)
            p.drawString(x, y - 1.05 * inch, f"${tile['price']:.2f}/sq ft | {tile['size']}")
            p.drawString(x, y - 1.15 * inch, torino_code)
    p.save()
    buffer.seek(0)
    return buffer

def generate_work_order_pdf(project_id):
    project = get_project_by_id(project_id)
    if not project:
        return None
    tile = get_tile_by_code(project['torino_code'])
    if not tile:
        return None
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    p.setFont("Helvetica-Bold", 16)
    p.drawString(1 * inch, height - 1 * inch, "Work Order")
    p.setFont("Helvetica", 12)
    y = height - 1.5 * inch
    p.drawString(1 * inch, y, f"Tile: {tile['name']}")
    y -= 0.2 * inch
    p.drawString(1 * inch, y, f"Size: {tile['size']}")
    y -= 0.2 * inch
    p.drawString(1 * inch, y, f"Sq Ft: {project['sq_ft']}")
    y -= 0.2 * inch
    p.drawString(1 * inch, y, f"Address: {project['address']}")
    y -= 0.2 * inch
    p.drawString(1 * inch, y, f"Date: {project['install_date']}")
    y -= 0.2 * inch
    p.drawString(1 * inch, y, f"Installer Fee: ${project['installer_fee']:.2f}")
    if project['budget']:
        y -= 0.2 * inch
        p.drawString(1 * inch, y, f"Budget: ${project['budget']:.2f}")
    if project['schedule']:
        y -= 0.2 * inch
        p.drawString(1 * inch, y, f"Schedule: {project['schedule'][:50]}...")
    qr = qrcode.QRCode(version=1, box_size=5, border=1)
    qr.add_data(f"finish/{project_id}")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)
    p.drawImage(qr_buffer, 5 * inch, height - 2 * inch, width=1 * inch, height=1 * inch)
    p.save()
    buffer.seek(0)
    return buffer

@app.route('/')
def showroom():
    if 'user' in session:
        return redirect(url_for('admin'))
    page = 1
    per_page = 9
    tiles = get_tiles(page, per_page, color_group='White')
    html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Torino Tile Showroom</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Open+Sans:wght@300;400&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Open Sans', sans-serif; background-color: #f8f3f0; color: #4a4a4a; margin: 0; padding: 0; }
        h1 { font-family: 'Playfair Display', serif; color: #8a7d6f; font-size: 2.5rem;@app.route('/installer_finish/<project_id>')
def installer_finish(project_id):
    project = get_project_by_id(project_id)
    if not project:
        return "Project not found.", 404
    html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Finish Install - Torino Tile</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f3f0; font-family: 'Open Sans', sans-serif; }
      <style>
    body { background-color: \#f8f3f0; font-family: 'Open Sans', sans-serif; }
    .camera-container { text-align: center; padding: 2rem; }
    #preview { width: 100%; max-height: 400px; object-fit: cover; border-radius: 8px; }
</style>
        #preview { width: 100%; max-height: 400px; object-fit: cover; border-radius: 8px; }
    </style>
</head>
<body>
    <div class="container my-5">
        <h2 style="font-family: 'Playfair Display'; color: #8a7d6f; text-align: center;">Finish Job: {{ project.client_name }}</h2>
        <p class="text-center">Address: {{ project.address }} | Tile: {{ project.torino_code }}</p>
        <div class="camera-container">
            <input type="file" id="photoInput" accept="image/*" capture="camera" style="display: none;">
            <img id="preview" style="display: none;" alt="Preview of installation photo" loading="lazy">
            <button class="btn btn-primary mt-3" onclick="takePhoto()" aria-label="Take photo to finish job">Take Photo</button>
            <button class="btn btn-success mt-2" onclick="uploadPhoto('{{ project_id }}')" style="display: none;" id="uploadBtn">Upload & Finish</button>
        </div>
    </div>
    <script>
        function takePhoto() {
            document.getElementById('photoInput').click();
        }
        document.getElementById('photoInput').addEventListener('change', e => {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = e => {
                    document.getElementById('preview').src = e.target.result;
                    document.getElementById('preview').style.display = 'block';
                    document.getElementById('uploadBtn').style.display = 'inline-block';
                };
                reader.readAsDataURL(file);
            }
        });
        function uploadPhoto(projectId) {
            const formData = new FormData();
            formData.append('photo', document.getElementById('photoInput').files[0]);
            fetch(`/installer_upload/${projectId}`, { method: 'POST', body: formData })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('Photo uploaded! Job complete.');
                        window.close();
                    } else {
                        alert('Upload failed.');
                    }
                });
        }
    </script>
</body>
</html>
    '''
    return render_template_string(html, project=project, project_id=project_id)

@app.route('/installer_upload/<project_id>', methods=['POST'])
def installer_upload(project_id):
    if 'photo' in request.files:
        photo_file = request.files['photo']
        if upload_photo(int(project_id), photo_file):
            return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/admin/upload_photo', methods=['POST'])
def admin_upload_photo():
    tile_code = request.form.get('tile_code')
    notes = request.form.get('notes', '')
    if 'photo' in request.files and tile_code:
        photo_file = request.files['photo']
        project = get_project_by_torino_code(tile_code)
        if not project:
            add_project_stub(tile_code, notes)
            project_id = get_latest_project_id(tile_code)
        else:
            project_id = project['id']
        if project_id and upload_photo(project_id, photo_file):
            return jsonify({'message': 'Photo uploaded successfully.'})
    return jsonify({'message': 'Upload failed.'}), 400

@app.route('/admin/generate_work_order', methods=['POST'])
def admin_generate_work_order():
    data = request.json
    notes = data.get('notes', '')
    proj_id = add_project(
        data['tile_code'], data['client_name'], data['address'],
        float(data['sq_ft']), data['install_date'], float(data['installer_fee']),
        notes, data.get('client_id'), data.get('budget'), data.get('schedule')
    )
    if proj_id:
        buffer = generate_work_order_pdf(proj_id)
        if buffer:
            return send_file(buffer, as_attachment=True, download_name='work_order.pdf', mimetype='application/pdf')
    return "Error generating work order.", 400

@app.route('/generate_sticker/<code>')
def generate_sticker(code):
    buffer = generate_sticker_pdf(code)
    if buffer:
        return send_file(buffer, as_attachment=True, download_name='stickers.pdf', mimetype='application/pdf')
    return "Sticker generation failed.", 400

@app.route('/process_voice', methods=['POST'])
def process_voice():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Login required.'})

    text = request.json.get('text', '').lower().strip()
    if not text:
        return jsonify({'success': False, 'message': 'No text received.'})

    if 'client_guide' not in session:
        session['client_guide'] = {'step': 0, 'data': {}}

    state = session['client_guide']
    step = state['step']

    if any(word in text for word in ['cancel', 'stop', 'never mind']):
        session['client_guide'] = {'step': 0, 'data': {}}
        return jsonify({'success': True, 'message': 'Client creation cancelled. What else can I help with?', 'reset': True})

    prompts = [
        "Last Name?",
        "First Name?",
        "Address, including street, city, state, and zip?",
        "Phone number?",
        "Email address?"
    ]

    if step == 0:
        state['data']['last_name'] = text.title()
        spelled = spell_out(state['data']['last_name'])
        state['step'] = 1
        session['client_guide'] = state
        return jsonify({
            'success': True,
            'message': f"You said {state['data']['last_name']}. Confirm spelling: {spelled}. Is that correct? Say 'yes' or correct it.",
            'tts': f"Absolutely, let's start a new client profile! Please answer the following questions. {prompts[0]}",
            'next_step': 0
        })

    elif step == 1:
        if 'yes' in text or 'correct' in text:
            state['step'] = 2
            session['client_guide'] = state
            return jsonify({
                'success': True,
                'message': f"Great! Now, {prompts[step]}",
                'tts': f"Perfect. {prompts[step]}",
                'next_step': step
            })
        else:
            state['data']['last_name'] = text.title()
            spelled = spell_out(state['data']['last_name'])
            return jsonify({
                'success': True,
                'message': f"Got it, {state['data']['last_name']}. Spelling: {spelled}. Correct now?",
                'tts': f"Got it. Confirm spelling: {spelled}. Is that correct?",
                'next_step': 1
            })

    elif 2 <= step <= 4:
        key_map = {2: 'first_name', 3: 'address', 4: 'phone'}
        key = key_map[step]
        state['data'][key] = text
        state['step'] += 1
        session['client_guide'] = state

        if step == 4:
            state['data']['email'] = text
            full_name = f"{state['data']['first_name']} {state['data']['last_name']}"
            client_id = add_client(full_name, state['data']['address'], state['data']['phone'], state['data']['email'])
            if client_id:
                session['client_guide'] = {'step': 0, 'data': {}}
                return jsonify({
                    'success': True,
                    'message': f"Perfect! Client profile created for {full_name}. ID: {client_id}. Ready for an estimate?",
                    'tts': f"Client profile created for {full_name}. What would you like to do next?",
                    'client_id': client_id,
                    'reset': True
                })
            else:
                return jsonify({'success': False, 'message': 'Error creating client. Try again.'})

        return jsonify({
            'success': True,
            'message': f"Noted: {text}. Now, {prompts[step]}",
            'tts': f"{prompts[step]}",
            'next_step': step
        })

    if state['step'] > 0:
        return jsonify({'success': False, 'message': 'Please complete the client profile first.'})

    return jsonify({'success': False, 'message': 'Try: "create new client profile" to start.'})@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        stored_hash = get_user(username)
        if stored_hash and check_password_hash(stored_hash, password):
            session['user'] = username
            return redirect(url_for('admin'))
        return "Invalid credentials.", 401
    html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Torino Tile</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body style="background-color: #f8f3f0;">
    <div class="container my-5">
        <div class="row justify-content-center">
            <div class="col-md-4">
                <h2 class="text-center" style="font-family: 'Playfair Display'; color: #8a7d6f;">Staff Login</h2>
                <form method="post">
                    <div class="mb-3">
                        <input type="text" class="form-control" name="username" placeholder="Username" required>
                    </div>
                    <div class="mb-3">
                        <input type="password" class="form-control" name="password" placeholder="Password" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Enter</button>
                </form>
            </div>
        </div>
    </div>
</body>
</html>
    '''
    return render_template_string(html)

@app.route('/client_login', methods=['GET', 'POST'])
def client_login():
    if request.method == 'POST':
        session['client_id'] = 1
        return redirect(url_for('showroom'))
    html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Client Login - Torino Tile</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body style="background-color: #f8f3f0;">
    <div class="container my-5">
        <div class="row justify-content-center">
            <div class="col-md-4">
                <h2 class="text-center" style="font-family: 'Playfair Display'; color: #8a7d6f;">Client Login</h2>
                <form method="post">
                    <div class="mb-3">
                        <input type="email" class="form-control" name="email" placeholder="Email" required>
                    </div>
                    <div class="mb-3">
                        <input type="password" class="form-control" name="password" placeholder="Password" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Enter</button>
                </form>
            </div>
        </div>
    </div>
</body>
</html>
    '''
    return render_template_string(html)

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('client_id', None)
    session.pop('favorites', None)
    return redirect(url_for('showroom'))

if __name__ == '__main__':
    app.run(debug=True)