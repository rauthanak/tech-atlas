"""Sign in, sign out, who am I, change my password (services/auth). Plain
`def` endpoints, so the slow password check runs in the threadpool, and every
answer is JSON."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.services import auth

router = APIRouter()


class SignIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class NewPassword(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


@router.post("/auth/sign-in")
def sign_in(body: SignIn, response: Response) -> dict:
    token, session = auth.sign_in(body.email, body.password)
    response.headers.append("set-cookie", auth.cookie(f"{session['role']}.{token}", auth.SESSION_HOURS * 3600))
    return auth.me(session)


@router.post("/auth/sign-out")
def sign_out(request: Request, response: Response) -> dict:
    """Works with no cookie or an old one too: the browser ends signed out either way."""
    token = auth.token_of(request)
    if token:
        auth.sign_out(token)
    response.headers.append("set-cookie", auth.cookie("", 0))
    return {"signed_out": True}


@router.get("/auth/me")
def me() -> dict:
    return auth.me(auth.CURRENT.get())


@router.post("/auth/password")
def change_password(body: NewPassword) -> dict:
    return auth.change_password(auth.CURRENT.get(), body.current, body.new)
