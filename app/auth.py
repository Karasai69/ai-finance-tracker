"""Регистрация, вход и проверка пользователя в каждом запросе.

Токен принимается двумя способами:
- cookie access_token (её ставит сайт при входе, JavaScript её не видит — защита от кражи через XSS);
- заголовок Authorization: Bearer <токен> (удобно для /docs и других клиентов).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Budget, Transaction, User
from app.ratelimit import login_limiter, register_limiter
from app.schemas import AccountDelete, AuthResponse, Credentials, PasswordChange, UserOut
from app.security import create_token, hash_password, password_stamp, read_claims, verify_password

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


def _issue(response: Response, user: User) -> str:
    token = create_token(user.id, stamp=password_stamp(user.password_hash))
    _set_cookie(response, token)
    return token


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

    claims = read_claims(token) if token else None
    user = db.get(User, claims[0]) if claims else None
    # Токен, выданный до смены пароля, больше не действует
    if user is None or claims[1] != password_stamp(user.password_hash):
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
    token = _issue(response, user)
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
    token = _issue(response, user)
    return AuthResponse(user=UserOut.model_validate(user), access_token=token)


@router.post("/logout", status_code=204)
def logout():
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, samesite="lax", secure=settings.cookie_secure)
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


def _check_password(user: User, password: str, request: Request) -> None:
    """Проверка текущего пароля перед опасными действиями — с тем же лимитом попыток, что и вход."""
    key = f"{_client_ip(request)}|{user.email}"
    if login_limiter.is_blocked(key):
        minutes = max(1, login_limiter.retry_after(key) // 60)
        raise _too_many(login_limiter, key, f"Слишком много попыток. Попробуйте через {minutes} мин.")
    if not verify_password(password, user.password_hash):
        login_limiter.hit(key)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный текущий пароль")
    login_limiter.reset(key)


@router.post("/password", response_model=AuthResponse)
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Смена пароля. Остальные устройства выходят из аккаунта, это — остаётся."""
    _check_password(user, body.current_password, request)
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Новый пароль совпадает с текущим")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    token = _issue(response, user)
    return AuthResponse(user=UserOut.model_validate(user), access_token=token)


@router.delete("/account", status_code=204)
def delete_account(
    body: AccountDelete,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удаляет аккаунт и все его данные без возможности восстановления."""
    _check_password(user, body.password, request)
    db.execute(delete(Transaction).where(Transaction.user_id == user.id))
    db.execute(delete(Budget).where(Budget.user_id == user.id))
    db.delete(user)
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, samesite="lax", secure=settings.cookie_secure)
    return response
