import sqlite3
import os
import pathlib

# connect to db
connect = sqlite3.connect("db/database.db")
cursor = connect.cursor()

# init tables
loadouts = """
CREATE TABLE INFO (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT
)
"""

sites = """
CREATE TABLE INFO (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT
)
"""

apps = """
CREATE TABLE INFO (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT
)
"""

loadoutsites = """
CREATE TABLE INFO (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT
)
"""

loadoutapps = """
CREATE TABLE INFO (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT
)
"""

cursor.execute(table)
connect.commit()
