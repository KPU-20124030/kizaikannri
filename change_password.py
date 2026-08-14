import getpass
import os
import sqlite3
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(
    os.environ.get(
        "KIZAIKANNRI_DATABASE_PATH",
        BASE_DIR / "kizaikannri.db",
    )
)


def main():
    if len(sys.argv) != 2:
        print("使い方: python change_password.py ユーザー名")
        raise SystemExit(1)

    username = sys.argv[1].strip()
    password = getpass.getpass("新しいパスワード: ")
    confirmation = getpass.getpass("新しいパスワード（確認）: ")

    if len(password) < 8:
        print("パスワードは8文字以上にしてください。")
        raise SystemExit(1)

    if password != confirmation:
        print("確認用パスワードが一致しません。")
        raise SystemExit(1)

    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.execute(
        """
        UPDATE users
        SET password_hash = ?
        WHERE username = ?
        """,
        (generate_password_hash(password), username),
    )
    connection.commit()
    connection.close()

    if cursor.rowcount == 0:
        print(f"ユーザー {username} が見つかりません。")
        raise SystemExit(1)

    print(f"ユーザー {username} のパスワードを変更しました。")


if __name__ == "__main__":
    main()
