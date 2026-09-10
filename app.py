import sqlite3
import json
import os
import hashlib
from datetime import datetime, timedelta

from flask import Flask, redirect, url_for, session, render_template, request, jsonify
from authlib.integrations.flask_client import OAuth
from flask_session import Session
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(basedir, "tasks.db")

print("CLIENT_ID:", os.getenv("GOOGLE_CLIENT_ID"))
# --- Google OAuth ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"}
)

# --- Почта ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
mail = Mail(app)

app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY")
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False

UPLOAD_FOLDER = os.path.join('static', 'img')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

Session(app)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


DEFAULT_CALENDARS = [
    ("Генеральная уборка", "cleaning_general"),
    ("Уборка кухни", "cleaning_kitchen"),
    ("Готовка", "cooking"),
]

MEMBER_COLORS = ["#007bff", "#e67e22", "#9b59b6", "#1abc9c", "#e84393", "#f1c40f", "#16a085"]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS calendars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            calendar_type TEXT DEFAULT 'custom',
            owner_email TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS calendar_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_id INTEGER NOT NULL,
            user_email TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            UNIQUE(calendar_id, user_email),
            FOREIGN KEY(calendar_id) REFERENCES calendars(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            note TEXT,
            shift_date TEXT,
            start_time TEXT,
            end_time TEXT,
            user_email TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            created_by TEXT,
            FOREIGN KEY(calendar_id) REFERENCES calendars(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()


init_db()


# --- Вспомогательные функции для календарей ---

def ensure_default_calendars(user_email):
    """Создаёт дефолтный набор календарей при первом входе пользователя."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM calendar_members WHERE user_email=?", (user_email,))
    has_any = c.fetchone()[0] > 0
    if not has_any:
        for name, ctype in DEFAULT_CALENDARS:
            c.execute(
                "INSERT INTO calendars (name, calendar_type, owner_email) VALUES (?, ?, ?)",
                (name, ctype, user_email)
            )
            cal_id = c.lastrowid
            c.execute(
                "INSERT INTO calendar_members (calendar_id, user_email, role) VALUES (?, ?, 'owner')",
                (cal_id, user_email)
            )
        conn.commit()
    conn.close()


def get_user_calendars(user_email):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT calendars.id, calendars.name, calendars.calendar_type, calendars.owner_email,
               calendar_members.role
        FROM calendars
        JOIN calendar_members ON calendars.id = calendar_members.calendar_id
        WHERE calendar_members.user_email = ?
        ORDER BY calendars.id
    """, (user_email,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def is_calendar_member(calendar_id, user_email):
    if not calendar_id or not user_email:
        return False
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM calendar_members WHERE calendar_id=? AND user_email=?", (calendar_id, user_email))
    row = c.fetchone()
    conn.close()
    return row is not None


def get_calendar_members(calendar_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_email, role FROM calendar_members WHERE calendar_id=? ORDER BY id", (calendar_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def member_color(email, members):
    """Стабильный цвет для участника — по его позиции в списке участников календаря."""
    emails = [m['user_email'] for m in members]
    if email in emails:
        idx = emails.index(email)
    else:
        idx = int(hashlib.md5(email.encode()).hexdigest(), 16)
    return MEMBER_COLORS[idx % len(MEMBER_COLORS)]


def send_deadline_notifications(user_email):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT title, shift_date FROM shifts WHERE user_email=? AND completed=0", (user_email,))
    shifts = c.fetchall()
    conn.close()

    tomorrow = (datetime.now() + timedelta(days=1)).date()
    today = datetime.now().date()

    message_text = ""
    for s in shifts:
        title, deadline = s["title"], s["shift_date"]
        if not deadline:
            continue
        try:
            deadline_date = datetime.strptime(deadline, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        if deadline_date == tomorrow:
            message_text += f"Смена «{title}» — завтра ({deadline}).\n"
        elif deadline_date == today:
            message_text += f"Сегодня смена «{title}» ({deadline}).\n"

    if message_text:
        try:
            msg = Message(
                subject="Напоминание о смене — ShiftChu",
                sender=app.config['MAIL_USERNAME'],
                recipients=[user_email],
                body=message_text
            )
            mail.send(msg)
        except Exception as e:
            print("Ошибка при отправке письма:", e)


# --- Главная страница ---
@app.route('/')
def index():
    user = session.get('user')
    calendars = []
    selected_calendar = None
    selected_calendar_id = request.args.get('calendar_id', type=int)
    view_mode = request.args.get('view', 'shared')
    if view_mode not in ('shared', 'personal'):
        view_mode = 'shared'

    shifts_for_container = []
    shifts_for_calendar = []
    shifts_due_tomorrow = []
    members = []

    if user:
        ensure_default_calendars(user['email'])
        send_deadline_notifications(user['email'])
        calendars = get_user_calendars(user['email'])

        if not selected_calendar_id and calendars:
            selected_calendar_id = calendars[0]['id']

        if selected_calendar_id and is_calendar_member(selected_calendar_id, user['email']):
            selected_calendar = next((c for c in calendars if c['id'] == selected_calendar_id), None)
            members = get_calendar_members(selected_calendar_id)

            conn = get_db()
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            if view_mode == 'personal':
                c.execute(
                    "SELECT * FROM shifts WHERE calendar_id=? AND user_email=?",
                    (selected_calendar_id, user['email'])
                )
            else:
                c.execute("SELECT * FROM shifts WHERE calendar_id=?", (selected_calendar_id,))
            rows = c.fetchall()
            conn.close()

            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)

            for s in rows:
                deadline_str = s['shift_date']
                overdue = False
                if deadline_str:
                    try:
                        deadline_date = datetime.strptime(deadline_str, "%Y-%m-%d").date()
                        overdue = deadline_date < today and s['completed'] == 0
                    except (ValueError, TypeError):
                        pass

                if s['completed']:
                    color = "#28a745"
                elif overdue:
                    color = "#dc3545"
                elif view_mode == 'shared':
                    color = member_color(s['user_email'], members)
                else:
                    color = "#007bff"

                shifts_for_calendar.append({
                    "id": s['id'],
                    "title": f"{s['title']} — {s['user_email'].split('@')[0]}",
                    "raw_title": s['title'],
                    "note": s['note'] or "",
                    "start": (s['shift_date'] + ("T" + s['start_time'] if s['start_time'] else "")) if deadline_str else None,
                    "completed": s['completed'],
                    "overdue": overdue,
                    "color": color
                })

                if s['completed'] == 0:
                    shifts_for_container.append({
                        "id": s['id'],
                        "title": s['title'],
                        "note": s['note'],
                        "shift_date": deadline_str,
                        "start_time": s['start_time'],
                        "end_time": s['end_time'],
                        "assignee": s['user_email'],
                        "completed": s['completed'],
                        "overdue": overdue
                    })

                if deadline_str:
                    try:
                        if datetime.strptime(deadline_str, "%Y-%m-%d").date() == tomorrow:
                            shifts_due_tomorrow.append({"id": s['id'], "title": s['title'], "shift_date": deadline_str})
                    except (ValueError, TypeError):
                        pass

    return render_template(
        'index.html',
        user=user,
        calendars=calendars,
        selected_calendar=selected_calendar,
        selected_calendar_id=selected_calendar_id,
        view_mode=view_mode,
        members=members,
        shifts=shifts_for_container,
        shifts_json=json.dumps(shifts_for_calendar),
        shifts_due_tomorrow=shifts_due_tomorrow
    )


# --- Календари ---
@app.route('/calendars/create', methods=['POST'])
def create_calendar():
    user = session.get('user')
    if not user:
        return redirect('/login')

    name = (request.form.get('name') or '').strip()
    if not name:
        return redirect('/')

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO calendars (name, calendar_type, owner_email) VALUES (?, 'custom', ?)",
              (name, user['email']))
    cal_id = c.lastrowid
    c.execute("INSERT INTO calendar_members (calendar_id, user_email, role) VALUES (?, ?, 'owner')",
              (cal_id, user['email']))
    conn.commit()
    conn.close()

    return redirect(f'/?calendar_id={cal_id}')


@app.route('/calendars/<int:calendar_id>/invite', methods=['POST'])
def invite_member(calendar_id):
    user = session.get('user')
    if not user or not is_calendar_member(calendar_id, user['email']):
        return redirect('/')

    friend_email = (request.form.get('email') or '').strip().lower()
    if friend_email:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO calendar_members (calendar_id, user_email, role) VALUES (?, ?, 'member')",
            (calendar_id, friend_email)
        )
        conn.commit()
        conn.close()

    return redirect(f'/?calendar_id={calendar_id}')


@app.route('/calendars/<int:calendar_id>/members')
def calendar_members_json(calendar_id):
    user = session.get('user')
    if not user or not is_calendar_member(calendar_id, user['email']):
        return jsonify([])
    return jsonify(get_calendar_members(calendar_id))


# --- Профиль пользователя ---
@app.route('/profile')
def profile():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    calendars = get_user_calendars(user['email'])

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM shifts WHERE user_email = ?", (user['email'],))
    rows = c.fetchall()
    conn.close()

    today = datetime.now().date()
    shifts_list = []
    for s in rows:
        completed = s['completed'] == 1
        overdue = False
        if s['shift_date']:
            try:
                deadline_date = datetime.strptime(s['shift_date'], "%Y-%m-%d").date()
                overdue = not completed and deadline_date < today
            except (ValueError, TypeError):
                pass
        shifts_list.append({
            "id": s['id'],
            "title": s['title'],
            "subject": s['note'],
            "deadline": s['shift_date'],
            "completed": completed,
            "overdue": overdue
        })

    return render_template('profile.html', user=user, tasks=shifts_list, calendars=calendars)


@app.route('/edit-profile', methods=['GET', 'POST'])
def edit_profile():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_name = request.form.get('name')
        if new_name:
            user['name'] = new_name

        file = request.files.get('avatar')
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            user['avatar'] = '/' + filepath.replace('\\', '/')

        session['user'] = user
        return redirect(url_for('profile'))

    return render_template('edit_profile.html', user=user)


# --- Добавление смены ---
@app.route('/add', methods=['POST'])
def add_shift():
    user = session.get('user')
    if not user:
        return redirect('/login')

    calendar_id = request.form.get('calendar_id', type=int)
    if not calendar_id or not is_calendar_member(calendar_id, user['email']):
        return redirect('/')

    title = request.form.get('title', '').strip()
    if not title:
        return redirect(f'/?calendar_id={calendar_id}')

    note = request.form.get('note', '')
    shift_date = request.form.get('shift_date', '')
    start_time = request.form.get('start_time', '')
    end_time = request.form.get('end_time', '')
    assignee = request.form.get('assignee') or user['email']

    # назначать смену можно только участнику этого же календаря
    if not is_calendar_member(calendar_id, assignee):
        assignee = user['email']

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO shifts (calendar_id, title, note, shift_date, start_time, end_time, user_email, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (calendar_id, title, note, shift_date, start_time, end_time, assignee, user['email'])
    )
    conn.commit()
    conn.close()

    return redirect(f'/?calendar_id={calendar_id}')


def _shift_calendar_id(shift_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT calendar_id FROM shifts WHERE id=?", (shift_id,))
    row = c.fetchone()
    conn.close()
    return row['calendar_id'] if row else None


@app.route('/complete/<int:shift_id>', methods=['POST'])
def complete_task(shift_id):
    user = session.get('user')
    if not user:
        return jsonify({"error": "Не авторизован"}), 401
    cal_id = _shift_calendar_id(shift_id)
    if not is_calendar_member(cal_id, user['email']):
        return jsonify({"error": "Нет доступа"}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE shifts SET completed = 1 WHERE id=?", (shift_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/undo/<int:shift_id>', methods=['POST'])
def undo_task(shift_id):
    user = session.get('user')
    if not user:
        return jsonify({"error": "Не авторизован"}), 401
    cal_id = _shift_calendar_id(shift_id)
    if not is_calendar_member(cal_id, user['email']):
        return jsonify({"error": "Нет доступа"}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE shifts SET completed = 0 WHERE id = ?", (shift_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/delete/<int:shift_id>', methods=['POST'])
def delete_task(shift_id):
    user = session.get('user')
    if not user:
        return jsonify({"error": "Не авторизован"}), 401
    cal_id = _shift_calendar_id(shift_id)
    if not is_calendar_member(cal_id, user['email']):
        return jsonify({"error": "Нет доступа"}), 403

    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM shifts WHERE id=?", (shift_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/edit/<int:shift_id>', methods=['GET', 'POST'])
def edit_task(shift_id):
    user = session.get('user')
    if not user:
        if request.method == 'POST':
            return jsonify({"error": "Не авторизован"}), 401
        return redirect('/login')

    cal_id = _shift_calendar_id(shift_id)
    if not is_calendar_member(cal_id, user['email']):
        if request.method == 'POST':
            return jsonify({"error": "Нет доступа"}), 403
        return redirect('/')

    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        title = data.get('title', '')
        note = data.get('subject', data.get('note', ''))
        shift_date = data.get('deadline', data.get('shift_date', ''))

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "UPDATE shifts SET title=?, note=?, shift_date=? WHERE id=?",
            (title, note, shift_date, shift_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})

    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, title, note, shift_date, calendar_id FROM shifts WHERE id=?", (shift_id,))
    shift = c.fetchone()
    conn.close()
    return render_template('edit.html', task=shift)


@app.route('/update-date/<int:shift_id>', methods=['POST'])
def update_task_deadline(shift_id):
    user = session.get('user')
    if not user:
        return jsonify({"error": "Не авторизован"}), 401
    cal_id = _shift_calendar_id(shift_id)
    if not is_calendar_member(cal_id, user['email']):
        return jsonify({"error": "Нет доступа"}), 403

    data = request.get_json(silent=True) or {}
    new_deadline = data.get('deadline')
    if not new_deadline:
        return jsonify({"error": "Дата не указана"}), 400

    # deadline может прийти как ISO со временем — берём только дату
    new_date = new_deadline.split('T')[0]

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE shifts SET shift_date=? WHERE id=?", (new_date, shift_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# --- Общий календарь (по умолчанию открывает первый календарь в режиме "общий") ---
@app.route('/shared-calendar')
def shared_calendar():
    user = session.get('user')
    if not user:
        return redirect('/login')
    calendars = get_user_calendars(user['email'])
    calendar_id = calendars[0]['id'] if calendars else ''
    return redirect(f'/?calendar_id={calendar_id}&view=shared')


# --- Авторизация ---
@app.route('/login')
def login():
    redirect_uri = url_for('authorize', _external=True)
    return google.authorize_redirect(redirect_uri, prompt='select_account')


@app.route('/authorize')
def authorize():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    session['user'] = {
        "email": user_info.get("email"),
        "name": user_info.get("name")
    }
    ensure_default_calendars(user_info.get("email"))
    return redirect('/')


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')


@app.route('/faq')
def faq():
    user = session.get('user')
    return render_template('faq.html', user=user)


if __name__ == '__main__':
    app.run(debug=True)
