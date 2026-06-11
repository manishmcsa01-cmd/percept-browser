import sqlite3
import json

db_path = "C:\\manish\\SchoolOfAI\\session9\\llm_gatewayV9\\gateway_v8.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("SELECT * FROM calls WHERE agent='researcher' ORDER BY id DESC LIMIT 10")
rows = cursor.fetchall()

for r in reversed(rows):
    d = dict(r)
    print(f"\n--- ID: {d.get('id')} | Status: {d.get('status')} | Duration: {d.get('latency_ms')}ms ---")
    print(d.get('error'))
    print(d.get('response')[:500] if d.get('response') else "NO RESPONSE")

conn.close()
