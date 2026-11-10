import re
from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.categories import kind_of, normalize_category


class ParsedItem(BaseModel):
    """Одна запись: расход, доход или долг."""

    date: date_type
    amount: float = Field(gt=0)
    category: str = "other"
    kind: str = "expense"
    description: str = Field(default="", max_length=300)

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, value):
        return normalize_category(value)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value):
        if isinstance(value, str):
            value = value.replace(" ", "").replace(" ", "").replace(",", ".")
        return value

    @model_validator(mode="after")
    def _kind_from_category(self):
        # Тип всегда следует из категории, чтобы данные не противоречили друг другу.
        self.kind = kind_of(self.category)
        self.amount = round(self.amount, 2)
        return self


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    date: date_type | None = None


class ParseResponse(BaseModel):
    source: str  # "ai" или "rules"
    items: list[ParsedItem]
    unparsed: list[str] = []
    warning: str | None = None


class SaveRequest(BaseModel):
    items: list[ParsedItem] = Field(min_length=1, max_length=100)
    raw_text: str | None = Field(default=None, max_length=2000)


class ImportRequest(BaseModel):
    csv: str = Field(min_length=1, max_length=1_000_000)


class ImportResponse(BaseModel):
    imported: int
    months: list[str]


class TransactionUpdate(BaseModel):
    date: date_type | None = None
    amount: float | None = Field(default=None, gt=0)
    category: str | None = None
    description: str | None = Field(default=None, max_length=300)


class TransactionOut(ParsedItem):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class CategoryTotal(BaseModel):
    category: str
    name: str
    kind: str
    total: float


class DayTotal(BaseModel):
    date: date_type
    expense: float
    income: float


class Summary(BaseModel):
    month: str
    income: float
    expense: float
    lent: float
    balance: float
    by_category: list[CategoryTotal]
    by_day: list[DayTotal]


# ---------- Вход в аккаунт ----------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError("Некорректный email")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str


class AuthResponse(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"
