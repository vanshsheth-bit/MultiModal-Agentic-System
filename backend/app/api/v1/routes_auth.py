from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.database import User
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    decode_refresh_token,
)


router = APIRouter(tags=["auth"])


@router.post("/login")
async def login(username: str, password: str, db: Session = Depends(get_db)) -> dict:
    user = authenticate_user(username, password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    user_id = user.get("id")
    tier = user.get("tier", "free")
    if user_id is not None:
        existing = db.query(User).filter(User.id == int(user_id)).first()
        if existing is None:
            db.add(
                User(
                    id=int(user_id),
                    username=username,
                    password_hash="",
                    tier=str(tier),
                )
            )
            db.commit()

    token = create_access_token(
        {
            "sub": username,
            "id": user_id,
            "tier": tier,
        }
    )
    return {"access_token": token, "token_type": "bearer"}


@router.post("/refresh")
async def refresh_token(
    refresh_token: str = Body(..., embed=True),
    db: Session = Depends(get_db),  # db reserved for future user/tier checks
) -> dict:
    payload = decode_refresh_token(refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_sub = payload.get("sub")
    if user_sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload",
        )

    new_access_token = create_access_token(
        {
            "sub": user_sub,
            "id": payload.get("id"),
            "tier": payload.get("tier", "free"),
        }
    )
    return {"access_token": new_access_token, "token_type": "bearer"}
