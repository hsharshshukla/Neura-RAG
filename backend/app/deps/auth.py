from fastapi import Depends, HTTPException, Header
from jose import JWTError, jwt

SECRET_KEY = "supersecretkey"
ALGORITHM = "HS256"

def get_current_user(token: str = Header(..., alias="Authorization")):
    try:
        payload = jwt.decode(token.replace("Bearer ", ""), SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
