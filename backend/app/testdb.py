import sqlite3
con = sqlite3.connect("chatbot.db")
print(con)
print(con.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall())
