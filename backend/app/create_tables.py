# backend/app/create_tables.py

from sqlmodel import SQLModel
from db import engine
import models

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

if __name__ == "__main__":
    create_db_and_tables()
    print("Tables created!")
