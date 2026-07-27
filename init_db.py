import sqlite3

connection = sqlite3.connect("kizaikanri.db")
connection.execute("PRAGMA foreign_keys = ON")

cursor = connection.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        status TEXT NOT NULL
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        equipment_id INTEGER NOT NULL,
        borrower TEXT NOT NULL,
        borrowed_at TEXT NOT NULL,
        returned_at TEXT,
        status TEXT NOT NULL,
        FOREIGN KEY (equipment_id) REFERENCES equipment (id)
    )
""")

cursor.execute("SELECT COUNT(*) FROM equipment")
equipment_count = cursor.fetchone()[0]

if equipment_count == 0:
    equipment_data = [
        ("ノートパソコン", "PC", "貸出可能"),
        ("モニター", "モニター", "貸出可能"),
        ("温度センサー", "センサー", "貸出可能")
    ]

    cursor.executemany("""
        INSERT INTO equipment (name, category, status)
        VALUES (?, ?, ?)
    """, equipment_data)

connection.commit()
connection.close()

print("機材テーブルと貸出履歴テーブルを作成しました。")