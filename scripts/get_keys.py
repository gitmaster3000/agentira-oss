
import sqlite3
import os

db_path = r"c:\agentira\data\agentira.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name, api_key FROM profiles LIMIT 5;")
    rows = cursor.fetchall()
    for row in rows:
        print(f"Name: {row[0]}, API Key: {row[1]}")
    conn.close()
else:
    print(f"DB not found at {db_path}")
