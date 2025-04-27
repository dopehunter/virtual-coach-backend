import os
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SUPABASE_JWT_SECRET")
ALGORITHM = "HS256"

if not SECRET_KEY:
    raise ValueError("SUPABASE_JWT_SECRET must be set in environment variables.")

# This will expect the token to be sent in the Authorization header as "Bearer <token>"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token") # tokenUrl is required but not used directly here

async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_aud": False}) # Supabase JWTs might not have standard 'aud'
        user_id: str | None = payload.get("sub") # 'sub' usually contains the user ID
        if user_id is None:
            raise credentials_exception
        return user_id
    except JWTError as e:
        print(f"JWT Error: {e}") # Log the error for debugging
        raise credentials_exception
    except Exception as e:
        print(f"Unexpected error during JWT decode: {e}") # Log unexpected errors
        raise credentials_exception 