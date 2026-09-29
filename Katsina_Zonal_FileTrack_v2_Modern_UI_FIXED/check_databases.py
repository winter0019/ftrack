import os
import sqlite3

ROOT = r"C:\Users\Broken-Window\Downloads\Entrepreneurship"

print("=" * 100)
print("SQLITE DATABASE INVENTORY")
print("=" * 100)

found = 0

for root, dirs, files in os.walk(ROOT):
    for filename in files:
        if not filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
            continue

        path = os.path.join(root, filename)

        try:
            conn = sqlite3.connect(path)
            cursor = conn.cursor()

            tables = cursor.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """).fetchall()

            print()
            print("-" * 100)
            print("DATABASE:", path)

            total_rows = 0

            if not tables:
                print("  No user tables found.")
            else:
                for (table,) in tables:
                    try:
                        count = cursor.execute(
                            f'SELECT COUNT(*) FROM "{table}"'
                        ).fetchone()[0]

                        print(f"  {table:<25} {count:>8} rows")
                        total_rows += count

                    except Exception as e:
                        print(f"  {table:<25} ERROR: {e}")

                print(f"  {'TOTAL ROWS':<25} {total_rows:>8}")

            conn.close()
            found += 1

        except Exception as e:
            print()
            print("-" * 100)
            print("DATABASE:", path)
            print("  ERROR:", e)

print()
print("=" * 100)
print(f"DONE - Found {found} SQLite database(s)")
print("=" * 100)