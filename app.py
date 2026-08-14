import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(
    os.environ.get(
        "KIZAIKANNRI_DATABASE_PATH",
        BASE_DIR / "kizaikannri.db",
    )
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "kizaikannri-development-key-change-me",
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

JST = timezone(timedelta(hours=9))


def get_current_time():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def get_db_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_database_schema():
    """既存DBを消さず、追加機能に必要な表だけを作成する。"""
    connection = get_db_connection()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            borrower TEXT NOT NULL,
            borrowed_at TEXT NOT NULL,
            returned_at TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (equipment_id) REFERENCES equipment (id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('student', 'admin'))
        );

        CREATE TABLE IF NOT EXISTS loan_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            loan_id INTEGER,
            requested_at TEXT NOT NULL,
            decided_at TEXT,
            returned_at TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (equipment_id) REFERENCES equipment (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (loan_id) REFERENCES loans (id)
        );

        CREATE INDEX IF NOT EXISTS idx_requests_equipment_status
        ON loan_requests (equipment_id, status);

        CREATE INDEX IF NOT EXISTS idx_requests_user
        ON loan_requests (user_id, id DESC);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_equipment_active_request
        ON loan_requests (equipment_id)
        WHERE status IN ('承認待ち', '貸出中');
        """
    )
    connection.commit()
    connection.close()


ensure_database_schema()


@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")

    if user_id is None:
        g.user = None
        return

    connection = get_db_connection()
    g.user = connection.execute(
        "SELECT id, username, display_name, role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    connection.close()

    if g.user is None:
        session.clear()


@app.before_request
def protect_post_requests():
    if request.method != "POST":
        return

    form_token = request.form.get("csrf_token", "")
    session_token = session.get("csrf_token", "")
    if not form_token or not session_token or not secrets.compare_digest(
        form_token, session_token
    ):
        flash("操作を確認できませんでした。ページを開き直してください。", "error")
        return redirect(url_for("index") if g.user else url_for("login"))


@app.context_processor
def add_template_helpers():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("ログインしてください。", "error")
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(**kwargs):
            if g.user["role"] != role:
                flash("このページを操作する権限がありません。", "error")
                return redirect(url_for("index"))
            return view(**kwargs)

        return wrapped_view

    return decorator


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        connection = get_db_connection()
        user = connection.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        user_count = connection.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]
        connection.close()

        if user is None or not check_password_hash(
            user["password_hash"], password
        ):
            if user_count == 0:
                flash("利用者が未登録です。先にinit_db.pyを実行してください。", "error")
            else:
                flash("ユーザー名またはパスワードが違います。", "error")
            return render_template("login.html", username=username)

        session.clear()
        session["user_id"] = user["id"]
        flash(f"{user['display_name']}さん、ログインしました。", "success")

        if user["role"] == "admin":
            return redirect(url_for("admin_requests"))
        return redirect(url_for("index"))

    return render_template("login.html", username="")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    flash("ログアウトしました。", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    keyword = request.args.get("keyword", "").strip()
    search_word = f"%{keyword}%"
    connection = get_db_connection()

    equipment_list = connection.execute(
        """
        SELECT
            equipment.*,
            my_request.id AS my_request_id,
            my_request.status AS my_request_status
        FROM equipment
        LEFT JOIN loan_requests AS my_request
          ON my_request.equipment_id = equipment.id
         AND my_request.user_id = ?
         AND my_request.status IN ('承認待ち', '貸出中')
        WHERE (? = '' OR equipment.name LIKE ? OR equipment.category LIKE ?)
        ORDER BY equipment.id
        """,
        (g.user["id"], keyword, search_word, search_word),
    ).fetchall()
    connection.close()

    return render_template(
        "index.html",
        equipment_list=equipment_list,
        keyword=keyword,
    )


@app.post("/request/<int:equipment_id>")
@role_required("student")
def request_loan(equipment_id):
    connection = get_db_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")
        equipment = connection.execute(
            "SELECT * FROM equipment WHERE id = ?",
            (equipment_id,),
        ).fetchone()

        if equipment is None:
            flash("機材が見つかりません。", "error")
        elif equipment["status"] != "貸出可能":
            flash("この機材は現在申請できません。", "error")
        else:
            connection.execute(
                """
                INSERT INTO loan_requests (
                    equipment_id,
                    user_id,
                    requested_at,
                    status
                )
                VALUES (?, ?, ?, '承認待ち')
                """,
                (equipment_id, g.user["id"], get_current_time()),
            )
            connection.execute(
                "UPDATE equipment SET status = '申請中' WHERE id = ?",
                (equipment_id,),
            )
            flash(f"{equipment['name']}の貸出を申請しました。", "success")

        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        flash("申請処理に失敗しました。もう一度お試しください。", "error")
    finally:
        connection.close()

    return redirect(url_for("my_requests"))


@app.route("/my-requests")
@role_required("student")
def my_requests():
    connection = get_db_connection()
    request_list = connection.execute(
        """
        SELECT
            loan_requests.*,
            equipment.name AS equipment_name,
            equipment.category
        FROM loan_requests
        JOIN equipment ON loan_requests.equipment_id = equipment.id
        WHERE loan_requests.user_id = ?
        ORDER BY loan_requests.id DESC
        """,
        (g.user["id"],),
    ).fetchall()
    connection.close()

    return render_template("my_requests.html", request_list=request_list)


@app.route("/admin/requests")
@role_required("admin")
def admin_requests():
    connection = get_db_connection()
    request_list = connection.execute(
        """
        SELECT
            loan_requests.*,
            equipment.name AS equipment_name,
            equipment.category,
            users.display_name,
            users.username
        FROM loan_requests
        JOIN equipment ON loan_requests.equipment_id = equipment.id
        JOIN users ON loan_requests.user_id = users.id
        ORDER BY
            CASE loan_requests.status
                WHEN '承認待ち' THEN 1
                WHEN '貸出中' THEN 2
                WHEN '却下' THEN 3
                ELSE 4
            END,
            loan_requests.id DESC
        """
    ).fetchall()
    connection.close()

    return render_template("admin_requests.html", request_list=request_list)


@app.post("/admin/requests/<int:request_id>/approve")
@role_required("admin")
def approve_request(request_id):
    connection = get_db_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")
        loan_request = connection.execute(
            """
            SELECT
                loan_requests.*,
                equipment.name AS equipment_name,
                equipment.status AS equipment_status,
                users.display_name
            FROM loan_requests
            JOIN equipment ON loan_requests.equipment_id = equipment.id
            JOIN users ON loan_requests.user_id = users.id
            WHERE loan_requests.id = ?
            """,
            (request_id,),
        ).fetchone()

        if loan_request is None:
            flash("申請が見つかりません。", "error")
        elif loan_request["status"] != "承認待ち":
            flash("この申請はすでに処理されています。", "error")
        elif loan_request["equipment_status"] != "申請中":
            flash("機材の状態が変わったため承認できません。", "error")
        else:
            approved_at = get_current_time()
            cursor = connection.execute(
                """
                INSERT INTO loans (
                    equipment_id,
                    borrower,
                    borrowed_at,
                    returned_at,
                    status
                )
                VALUES (?, ?, ?, NULL, '貸出中')
                """,
                (
                    loan_request["equipment_id"],
                    loan_request["display_name"],
                    approved_at,
                ),
            )
            connection.execute(
                """
                UPDATE loan_requests
                SET loan_id = ?, decided_at = ?, status = '貸出中'
                WHERE id = ?
                """,
                (cursor.lastrowid, approved_at, request_id),
            )
            connection.execute(
                "UPDATE equipment SET status = '貸出中' WHERE id = ?",
                (loan_request["equipment_id"],),
            )
            flash(
                f"{loan_request['display_name']}さんの"
                f"{loan_request['equipment_name']}の申請を承認しました。",
                "success",
            )

        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        flash("承認処理に失敗しました。", "error")
    finally:
        connection.close()

    return redirect(url_for("admin_requests"))


@app.post("/admin/requests/<int:request_id>/reject")
@role_required("admin")
def reject_request(request_id):
    connection = get_db_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")
        loan_request = connection.execute(
            """
            SELECT loan_requests.*, equipment.name AS equipment_name
            FROM loan_requests
            JOIN equipment ON loan_requests.equipment_id = equipment.id
            WHERE loan_requests.id = ?
            """,
            (request_id,),
        ).fetchone()

        if loan_request is None:
            flash("申請が見つかりません。", "error")
        elif loan_request["status"] != "承認待ち":
            flash("この申請はすでに処理されています。", "error")
        else:
            connection.execute(
                """
                UPDATE loan_requests
                SET decided_at = ?, status = '却下'
                WHERE id = ?
                """,
                (get_current_time(), request_id),
            )
            connection.execute(
                "UPDATE equipment SET status = '貸出可能' WHERE id = ?",
                (loan_request["equipment_id"],),
            )
            flash(f"{loan_request['equipment_name']}の申請を却下しました。", "success")

        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        flash("却下処理に失敗しました。", "error")
    finally:
        connection.close()

    return redirect(url_for("admin_requests"))


@app.post("/requests/<int:request_id>/return")
@login_required
def return_requested_equipment(request_id):
    connection = get_db_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")
        loan_request = connection.execute(
            """
            SELECT loan_requests.*, equipment.name AS equipment_name
            FROM loan_requests
            JOIN equipment ON loan_requests.equipment_id = equipment.id
            WHERE loan_requests.id = ?
            """,
            (request_id,),
        ).fetchone()

        if loan_request is None:
            flash("貸出情報が見つかりません。", "error")
        elif (
            g.user["role"] != "admin"
            and loan_request["user_id"] != g.user["id"]
        ):
            flash("この機材を返却する権限がありません。", "error")
        elif loan_request["status"] != "貸出中":
            flash("この機材は返却処理できません。", "error")
        else:
            returned_at = get_current_time()
            connection.execute(
                """
                UPDATE loan_requests
                SET returned_at = ?, status = '返却済み'
                WHERE id = ?
                """,
                (returned_at, request_id),
            )
            connection.execute(
                "UPDATE equipment SET status = '貸出可能' WHERE id = ?",
                (loan_request["equipment_id"],),
            )
            if loan_request["loan_id"] is not None:
                connection.execute(
                    """
                    UPDATE loans
                    SET returned_at = ?, status = '返却済み'
                    WHERE id = ?
                    """,
                    (returned_at, loan_request["loan_id"]),
                )
            flash(f"{loan_request['equipment_name']}を返却しました。", "success")

        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        flash("返却処理に失敗しました。", "error")
    finally:
        connection.close()

    if g.user["role"] == "admin":
        return redirect(url_for("admin_requests"))
    return redirect(url_for("my_requests"))


@app.route("/history")
@role_required("admin")
def history():
    connection = get_db_connection()
    loan_history = connection.execute(
        """
        SELECT
            loans.id,
            equipment.name AS equipment_name,
            equipment.category,
            loans.borrower,
            loans.borrowed_at,
            loans.returned_at,
            loans.status
        FROM loans
        JOIN equipment ON loans.equipment_id = equipment.id
        ORDER BY loans.id DESC
        """
    ).fetchall()
    connection.close()

    return render_template("history.html", loan_history=loan_history)


@app.route("/admin", methods=["GET", "POST"])
@role_required("admin")
def admin():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()

        if not name or not category:
            flash("機材名とカテゴリを入力してください。", "error")
            return redirect(url_for("admin"))

        connection = get_db_connection()
        connection.execute(
            """
            INSERT INTO equipment (name, category, status)
            VALUES (?, ?, '貸出可能')
            """,
            (name, category),
        )
        connection.commit()
        connection.close()

        flash(f"{name}を登録しました。", "success")
        return redirect(url_for("admin"))

    connection = get_db_connection()
    equipment_list = connection.execute(
        """
        SELECT
            equipment.*,
            EXISTS (
                SELECT 1
                FROM loan_requests
                WHERE loan_requests.equipment_id = equipment.id
                  AND loan_requests.status = '貸出中'
            ) AS has_active_request
        FROM equipment
        ORDER BY equipment.id
        """
    ).fetchall()
    connection.close()

    return render_template("admin.html", equipment_list=equipment_list)


@app.post("/admin/delete/<int:equipment_id>")
@role_required("admin")
def delete_equipment(equipment_id):
    connection = get_db_connection()
    equipment = connection.execute(
        "SELECT * FROM equipment WHERE id = ?",
        (equipment_id,),
    ).fetchone()

    if equipment is None:
        flash("機材が見つかりません。", "error")
    elif equipment["status"] != "貸出可能":
        flash("申請中または貸出中の機材は削除できません。", "error")
    else:
        try:
            connection.execute(
                "DELETE FROM equipment WHERE id = ?",
                (equipment_id,),
            )
            connection.commit()
            flash(f"{equipment['name']}を削除しました。", "success")
        except sqlite3.IntegrityError:
            connection.rollback()
            flash("履歴が残っている機材は削除できません。", "error")

    connection.close()
    return redirect(url_for("admin"))


@app.post("/admin/legacy-return/<int:equipment_id>")
@role_required("admin")
def return_legacy_equipment(equipment_id):
    """旧版で直接貸出されたデータを管理者が返却できるようにする。"""
    connection = get_db_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")
        equipment = connection.execute(
            "SELECT * FROM equipment WHERE id = ?",
            (equipment_id,),
        ).fetchone()
        active_request = connection.execute(
            """
            SELECT id FROM loan_requests
            WHERE equipment_id = ? AND status = '貸出中'
            """,
            (equipment_id,),
        ).fetchone()

        if equipment is None:
            flash("機材が見つかりません。", "error")
        elif equipment["status"] != "貸出中" or active_request is not None:
            flash("この機材は旧版の返却処理対象ではありません。", "error")
        else:
            returned_at = get_current_time()
            active_loan = connection.execute(
                """
                SELECT id FROM loans
                WHERE equipment_id = ? AND status = '貸出中'
                ORDER BY id DESC
                LIMIT 1
                """,
                (equipment_id,),
            ).fetchone()
            if active_loan is not None:
                connection.execute(
                    """
                    UPDATE loans
                    SET returned_at = ?, status = '返却済み'
                    WHERE id = ?
                    """,
                    (returned_at, active_loan["id"]),
                )
            connection.execute(
                "UPDATE equipment SET status = '貸出可能' WHERE id = ?",
                (equipment_id,),
            )
            flash(f"{equipment['name']}を返却済みにしました。", "success")

        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        flash("返却処理に失敗しました。", "error")
    finally:
        connection.close()

    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(debug=True)
