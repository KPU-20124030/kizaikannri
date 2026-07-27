import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for
)

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "kizaikanri.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "k-lend-development-key"
)

JST = timezone(timedelta(hours=9))


def get_current_time():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def get_db_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@app.route("/")
def index():
    keyword = request.args.get("keyword", "").strip()
    connection = get_db_connection()

    if keyword:
        search_word = f"%{keyword}%"

        equipment_list = connection.execute("""
            SELECT * FROM equipment
            WHERE name LIKE ? OR category LIKE ?
            ORDER BY id
        """, (search_word, search_word)).fetchall()
    else:
        equipment_list = connection.execute("""
            SELECT * FROM equipment
            ORDER BY id
        """).fetchall()

    connection.close()

    return render_template(
        "index.html",
        equipment_list=equipment_list,
        keyword=keyword
    )


@app.route("/borrow/<int:equipment_id>", methods=["POST"])
def borrow(equipment_id):
    borrower = request.form.get("borrower", "").strip()

    if not borrower:
        flash("利用者名を入力してください。", "error")
        return redirect(url_for("index"))

    connection = get_db_connection()

    equipment = connection.execute(
        "SELECT * FROM equipment WHERE id = ?",
        (equipment_id,)
    ).fetchone()

    if equipment is None:
        flash("機材が見つかりません。", "error")

    elif equipment["status"] != "貸出可能":
        flash("この機材は現在貸出中です。", "error")

    else:
        borrowed_at = get_current_time()

        connection.execute("""
            UPDATE equipment
            SET status = '貸出中'
            WHERE id = ?
        """, (equipment_id,))

        connection.execute("""
            INSERT INTO loans (
                equipment_id,
                borrower,
                borrowed_at,
                returned_at,
                status
            )
            VALUES (?, ?, ?, NULL, '貸出中')
        """, (equipment_id, borrower, borrowed_at))

        connection.commit()

        flash(
            f"{equipment['name']}を{borrower}さんに貸し出しました。",
            "success"
        )

    connection.close()
    return redirect(url_for("index"))


@app.route("/return/<int:equipment_id>", methods=["POST"])
def return_equipment(equipment_id):
    connection = get_db_connection()

    equipment = connection.execute(
        "SELECT * FROM equipment WHERE id = ?",
        (equipment_id,)
    ).fetchone()

    if equipment is None:
        flash("機材が見つかりません。", "error")

    elif equipment["status"] != "貸出中":
        flash("この機材は貸し出されていません。", "error")

    else:
        returned_at = get_current_time()

        connection.execute("""
            UPDATE equipment
            SET status = '貸出可能'
            WHERE id = ?
        """, (equipment_id,))

        active_loan = connection.execute("""
            SELECT id FROM loans
            WHERE equipment_id = ?
              AND status = '貸出中'
            ORDER BY id DESC
            LIMIT 1
        """, (equipment_id,)).fetchone()

        if active_loan is not None:
            connection.execute("""
                UPDATE loans
                SET returned_at = ?,
                    status = '返却済み'
                WHERE id = ?
            """, (returned_at, active_loan["id"]))

        connection.commit()

        flash(
            f"{equipment['name']}を返却しました。",
            "success"
        )

    connection.close()
    return redirect(url_for("index"))


@app.route("/history")
def history():
    connection = get_db_connection()

    loan_history = connection.execute("""
        SELECT
            loans.id,
            equipment.name AS equipment_name,
            equipment.category,
            loans.borrower,
            loans.borrowed_at,
            loans.returned_at,
            loans.status
        FROM loans
        JOIN equipment
          ON loans.equipment_id = equipment.id
        ORDER BY loans.id DESC
    """).fetchall()

    connection.close()

    return render_template(
        "history.html",
        loan_history=loan_history
    )


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()

        if not name or not category:
            flash("機材名とカテゴリを入力してください。", "error")
            return redirect(url_for("admin"))

        connection = get_db_connection()

        connection.execute("""
            INSERT INTO equipment (name, category, status)
            VALUES (?, ?, '貸出可能')
        """, (name, category))

        connection.commit()
        connection.close()

        flash(f"{name}を登録しました。", "success")
        return redirect(url_for("admin"))

    connection = get_db_connection()

    equipment_list = connection.execute("""
        SELECT * FROM equipment
        ORDER BY id
    """).fetchall()

    connection.close()

    return render_template(
        "admin.html",
        equipment_list=equipment_list
    )

@app.route("/admin/delete/<int:equipment_id>", methods=["POST"])
def delete_equipment(equipment_id):
    connection = get_db_connection()

    equipment = connection.execute(
        "SELECT * FROM equipment WHERE id = ?",
        (equipment_id,)
    ).fetchone()

    if equipment is None:
        flash("削除する機材が見つかりません。", "error")

    elif equipment["status"] == "貸出中":
        flash("貸出中の機材は削除できません。", "error")

    else:
        loan_count = connection.execute("""
            SELECT COUNT(*) AS count
            FROM loans
            WHERE equipment_id = ?
        """, (equipment_id,)).fetchone()["count"]

        if loan_count > 0:
            flash(
                "貸出履歴がある機材は削除できません。",
                "error"
            )
        else:
            connection.execute(
                "DELETE FROM equipment WHERE id = ?",
                (equipment_id,)
            )

            connection.commit()

            flash(
                f"{equipment['name']}を削除しました。",
                "success"
            )

    connection.close()
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(debug=True)