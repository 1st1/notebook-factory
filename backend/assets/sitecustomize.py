import sys
import pysqlite3

try:
    import sqlite3  # noqa: F401
except ImportError:
    sys.modules["sqlite3"] = pysqlite3
