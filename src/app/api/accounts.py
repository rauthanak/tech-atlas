"""Setup › People, for admins (the guard keeps leaders out): who may sign in,
their role, switching an account off, and a temporary password for someone
who forgot theirs (services/accounts)."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import accounts, auth

router = APIRouter()


class NewPerson(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(max_length=120)
    role: Literal["admin", "leader"]
    password: str = Field(max_length=200)


class PersonEdit(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "leader"] | None = None
    disabled: bool | None = None


class Temporary(BaseModel):
    password: str = Field(max_length=200)


@router.get("/accounts")
def list_people() -> dict:
    return {"accounts": accounts.everyone()}


@router.post("/accounts")
def add_person(body: NewPerson) -> dict:
    return accounts.add(body.email, body.name, body.role, body.password, auth.by())


@router.put("/accounts/{email}")
def edit_person(email: str, body: PersonEdit) -> dict:
    return accounts.update(email, body.model_dump(exclude_none=True), auth.by()["email"])


@router.post("/accounts/{email}/password")
def temporary_password(email: str, body: Temporary) -> dict:
    return accounts.set_temporary(email, body.password)
