import sqlite3
from typing import Any, Dict, Optional
from adapters.base import Adapter, AdapterError

class SqliteAdapter(Adapter):
    def __init__(self, db_path: str, overview_query: str, models_query: Optional[str] = None):
        import os
        if ".." in db_path or db_path.startswith("/"):
            # Only allow relative paths inside a designated directory or simply disallow traversal
            if ".." in db_path:
                raise ValueError("Path traversal not allowed in db_path")
        self.db_path = db_path
        self.overview_query = overview_query
        self.models_query = models_query

    def fetch(self) -> Dict[str, Any]:
        uri = f"file:{self.db_path}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            result = {}
            
            # Fetch overview
            cursor.execute(self.overview_query)
            row = cursor.fetchone()
            if row:
                result["overview"] = dict(row)
            else:
                result["overview"] = {}
                
            # Fetch models
            if self.models_query:
                cursor.execute(self.models_query)
                rows = cursor.fetchall()
                result["models"] = [dict(r) for r in rows]
            else:
                result["models"] = []
                
            return result
        except sqlite3.Error as e:
            raise AdapterError(f"SQLite error: {e}")
        except Exception as e:
            raise AdapterError(f"Failed to query database: {e}")
        finally:
            if 'conn' in locals():
                conn.close()
