from fastapi import Depends, HTTPException, Header
from jose import jwt, JWTError

SECRET_KEY = "supersecretkey"  # move to .env later
ALGORITHM = "HS256"

def get_current_user(authorization: str = Header(...)):
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
