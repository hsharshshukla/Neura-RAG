import os
from sqlmodel import create_engine, Session

# Always resolve to the absolute path of chatbot.db within app folder
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "chatbot.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL, echo=True)

def get_session():
    return Session(engine)
