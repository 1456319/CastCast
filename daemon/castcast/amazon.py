import os
import subprocess
import sqlite3
import tempfile
import json

def get_amazon_tokens():
    db_path = "/data/data/com.amazon.avod.thirdpartyclient/databases/map_data_storage.db"
    
    # We will copy the DB to a temporary file using su, so we can read it without root in Python
    tmp_dir = tempfile.gettempdir()
    local_db = os.path.join(tmp_dir, "amazon_map.db")
    
    # Use su to copy the file and change permissions so we can read it
    cmd = f"su -c 'cp {db_path} {local_db} && chmod 666 {local_db}'"
    subprocess.run(cmd, shell=True, capture_output=True)
    
    if not os.path.exists(local_db):
        return {"error": "Failed to copy Amazon database. Ensure device is rooted and su is granted."}
        
    try:
        conn = sqlite3.connect(local_db)
        cursor = conn.cursor()
        
        # Let's dynamically dump all tables and their contents to find where the auth tokens are
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        dump = {}
        for (table_name,) in tables:
            try:
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 10")
                columns = [description[0] for description in cursor.description]
                rows = cursor.fetchall()
                dump[table_name] = {"columns": columns, "rows": rows}
            except Exception as e:
                dump[table_name] = str(e)
                
        return dump
    except Exception as e:
        return {"error": str(e)}
    finally:
        if os.path.exists(local_db):
            os.remove(local_db)

if __name__ == '__main__':
    print(json.dumps(get_amazon_tokens(), indent=2))
