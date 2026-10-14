import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS rockets(id INTEGER PRIMARY KEY, type TEXT, specs TEXT);
CREATE TABLE IF NOT EXISTS payloads(id INTEGER PRIMARY KEY, type TEXT, mass REAL, orbit TEXT);
CREATE TABLE IF NOT EXISTS pads(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS maintenance(id INTEGER PRIMARY KEY, pad_id INT REFERENCES pads, d1 TEXT, d2 TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS launches(id INTEGER PRIMARY KEY, rocket_id INT REFERENCES rockets, payload_id INT REFERENCES payloads,
  orbit TEXT NOT NULL, pad_id INT REFERENCES pads, start_time TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY, fuel TEXT, volume REAL, remaining REAL, expiry TEXT);
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY, batch_id INT REFERENCES batches, launch_id INT REFERENCES launches, volume REAL, dt TEXT);
"""

def connect(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
