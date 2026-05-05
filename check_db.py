import sqlite3

def check_db():
    conn = sqlite3.connect('podcast_automation.db')
    cur = conn.cursor()
    print("=== Podcasts Processed in Database ===")
    try:
        cur.execute("SELECT DISTINCT podcast_name FROM episodes")
        rows = cur.fetchall()
        for row in rows:
            print("-", row[0])
        if not rows:
            print("(No podcasts recorded yet)")
    except Exception as e:
        print("Error:", e)
    conn.close()

if __name__ == "__main__":
    check_db()
