import sqlite3

def check():
    try:
        conn = sqlite3.connect('rooms.db')
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cur.fetchall()
        print("Tables:", tables)
        for table in tables:
            tname = table[0]
            cur.execute(f"PRAGMA table_info({tname});")
            print(f"Schema for {tname}:", cur.fetchall())
            cur.execute(f"SELECT * FROM {tname} LIMIT 5;")
            print(f"Data in {tname}:", cur.fetchall())
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    check()
