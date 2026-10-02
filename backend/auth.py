import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config import APP_URL, SECRET

router = APIRouter(prefix="/api/auth")
signer = URLSafeTimedSerializer(SECRET)
COOKIE = "nf_session"


def user(request: Request):
    try:
        return signer.loads(request.cookies.get(COOKIE, ""), salt="session", max_age=604800)
    except BadSignature:
        return None


def require_owner(request: Request):
    current = user(request)
    if not current:
        raise HTTPException(401, "Sign in with GitHub first")
    if current.get("login", "").lower() != "1st1":
        raise HTTPException(403, "Only 1st1 can edit notebooks")
    if request.headers.get("origin") != APP_URL:
        raise HTTPException(403, "Invalid request origin")
    return current


def cookie(response, name, value, age):
    response.set_cookie(
        name,
        value,
        max_age=age,
        httponly=True,
        secure=APP_URL.startswith("https://"),
        samesite="lax",
        path="/",
    )


@router.get("/me")
async def me(request: Request):
    current = user(request)
    return {
        "user": current,
        "can_edit": bool(current and current.get("login", "").lower() == "1st1"),
        "configured": bool(os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET")),
    }


@router.get("/login")
async def login():
    if not os.getenv("GITHUB_CLIENT_ID") or not os.getenv("GITHUB_CLIENT_SECRET"):
        raise HTTPException(503, "Configure GitHub OAuth credentials to sign in")
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(
        "https://github.com/login/oauth/authorize?"
        + urlencode(
            {
                "client_id": os.environ["GITHUB_CLIENT_ID"],
                "state": state,
                "redirect_uri": APP_URL + "/api/auth/callback",
                "scope": "read:user",
            }
        )
    )
    cookie(response, "nf_oauth", signer.dumps(state, salt="oauth"), 600)
    return response


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    try:
        expected = signer.loads(request.cookies.get("nf_oauth", ""), salt="oauth", max_age=600)
        if not state or not secrets.compare_digest(state, expected) or not code:
            raise ValueError()
    except (BadSignature, ValueError):
        raise HTTPException(400, "Invalid or expired OAuth state") from None
    async with httpx.AsyncClient(timeout=20) as client:
        token = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            json={
                "client_id": os.environ["GITHUB_CLIENT_ID"],
                "client_secret": os.environ["GITHUB_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": APP_URL + "/api/auth/callback",
            },
        )
        access = token.json().get("access_token")
        if token.status_code != 200 or not access:
            raise HTTPException(400, "GitHub sign-in failed; please try again")
        profile = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/vnd.github+json",
            },
        )
        if profile.status_code != 200:
            raise HTTPException(502, "Could not verify your GitHub account")
    data = profile.json()
    response = RedirectResponse(APP_URL, status_code=303)
    cookie(
        response,
        COOKIE,
        signer.dumps({"login": data["login"], "id": data["id"]}, salt="session"),
        604800,
    )
    response.delete_cookie("nf_oauth", path="/")
    return response


@router.post("/logout")
async def logout(request: Request):
    if request.headers.get("origin") != APP_URL:
        raise HTTPException(403, "Invalid request origin")
    response = RedirectResponse(APP_URL, status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response
