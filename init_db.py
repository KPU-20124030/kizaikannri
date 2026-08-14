import os
import secrets
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(
    os.environ.get(
        "KIZAIKANNRI_DATABASE_PATH",
        BASE_DIR / "kizaikannri.db",
    )
)


def add_user_if_missing(
    connection,
    username,
    password,
    display_name,
    role,
):
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO users (
            username,
            password_hash,
            display_name,
            role
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            username,
            generate_password_hash(password),
            display_name,
            role,
        ),
    )
    return cursor.rowcount == 1


connection = sqlite3.connect(DATABASE_PATH)
connection.execute("PRAGMA foreign_keys = ON")
cursor = connection.cursor()

cursor.executescript(
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

cursor.execute("SELECT COUNT(*) FROM equipment")
if cursor.fetchone()[0] == 0:
    cursor.executemany(
        """
        INSERT INTO equipment (name, category, status)
        VALUES (?, ?, '貸出可能')
        """,
        [
            ("ノートパソコン", "PC"),
            ("プロジェクター", "映像機器"),
            ("デジタルカメラ", "撮影機材"),
        ],
    )

admin_username = os.environ.get("KIZAIKANNRI_ADMIN_USERNAME", "admin")
admin_password = os.environ.get(
    "KIZAIKANNRI_ADMIN_PASSWORD",
    secrets.token_urlsafe(10),
)
student_username = os.environ.get("KIZAIKANNRI_STUDENT_USERNAME", "student")
student_password = os.environ.get(
    "KIZAIKANNRI_STUDENT_PASSWORD",
    secrets.token_urlsafe(10),
)

admin_created = add_user_if_missing(
    connection,
    admin_username,
    admin_password,
    "管理者",
    "admin",
)
student_created = add_user_if_missing(
    connection,
    student_username,
    student_password,
    "学生A",
    "student",
)

connection.commit()
connection.close()

print(f"データベースを準備しました: {DATABASE_PATH}")
if admin_created:
    print(f"管理者ユーザー: {admin_username}")
    print(f"管理者の初期パスワード: {admin_password}")
else:
    print(f"管理者ユーザー {admin_username} は登録済みです。")

if student_created:
    print(f"学生ユーザー: {student_username}")
    print(f"学生の初期パスワード: {student_password}")
else:
    print(f"学生ユーザー {student_username} は登録済みです。")

print("初期パスワードは控えたあと、change_password.pyで変更してください。")
