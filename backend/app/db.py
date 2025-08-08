from sqlmodel import create_engine, Session
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./chatbot.db")
engine = create_engine(DATABASE_URL, echo=True)

def get_session():
    return Session(engine)
