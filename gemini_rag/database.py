import sqlite3
from datetime import datetime
from config import DATABASE_PATH

def conn():
 c=sqlite3.connect(DATABASE_PATH); c.row_factory=sqlite3.Row; return c

def initialize_database():
 c=conn(); c.execute('''CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY AUTOINCREMENT,file_path TEXT UNIQUE NOT NULL,file_name TEXT NOT NULL,file_hash TEXT NOT NULL,file_size INTEGER,modified_time REAL,gemini_document_name TEXT,status TEXT NOT NULL DEFAULT 'indexed',indexed_at TEXT,error_message TEXT)'''); c.commit(); c.close()

def get_file(path):
 c=conn(); r=c.execute('SELECT * FROM files WHERE file_path=?',(str(path),)).fetchone(); c.close(); return r

def save_file(path,name,h,size,mtime,gemini=None,status='indexed',error=None):
 c=conn(); c.execute('''INSERT INTO files(file_path,file_name,file_hash,file_size,modified_time,gemini_document_name,status,indexed_at,error_message) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(file_path) DO UPDATE SET file_name=excluded.file_name,file_hash=excluded.file_hash,file_size=excluded.file_size,modified_time=excluded.modified_time,gemini_document_name=excluded.gemini_document_name,status=excluded.status,indexed_at=excluded.indexed_at,error_message=excluded.error_message''',(str(path),name,h,size,mtime,gemini,status,datetime.now().isoformat(),error)); c.commit(); c.close()

def get_all_files():
 c=conn(); r=c.execute('SELECT * FROM files ORDER BY file_path').fetchall(); c.close(); return r
