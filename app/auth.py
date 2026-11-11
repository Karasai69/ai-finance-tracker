"""Регистрация, вход и проверка пользователя в каждом запросе.

Токен принимается двумя способами:
- cookie access_token (её ставит сайт при входе, JavaScript её не видит — защита от кражи через XSS);
- заголовок Authorization: Bearer <токен> (удобно для /docs и других клиентов).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.ratelimit import login_limiter, register_limiter
from app.schemas import AuthResponse, Credentials, UserOut
from app.security import create_token, hash_password, read_token, verify_password

COOKIE_NAME = "access_token"

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.token_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(limiter, key: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        message,
        headers={"Retry-After": str(limiter.retry_after(key))},
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = None
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    if not token:
        token = request.cookies.get(COOKIE_NAME)

    user_id = read_token(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужно войти в аккаунт")
    return user


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    key = _client_ip(request)
    if register_limiter.is_blocked(key):
        raise _too_many(register_limiter, key, "Слишком много регистраций, попробуйте позже")
    register_limiter.hit(key)
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот email уже зарегистрирован")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id)
    _set_cookie(response, token)
    return AuthResponse(user=UserOut.model_validate(user), access_token=token)


@router.post("/login", response_model=AuthResponse)
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{_client_ip(request)}|{body.email}"
    if login_limiter.is_blocked(key):
        minutes = max(1, login_limiter.retry_after(key) // 60)
        raise _too_many(login_limiter, key, f"Слишком много попыток входа. Попробуйте через {minutes} мин.")
    user = db.scalar(select(User).where(User.email == body.email))
    # Одинаковое сообщение, чтобы нельзя было узнать, какие email зарегистрированы
    if user is None or not verify_password(body.password, user.password_hash):
        login_limiter.hit(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    login_limiter.reset(key)
    token = create_token(user.id)
    _set_cookie(response, token)
    return AuthResponse(user=UserOut.model_validate(user), access_token=token)


@router.post("/logout", status_code=204)
def logout():
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, samesite="lax", secure=settings.cookie_secure)
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
