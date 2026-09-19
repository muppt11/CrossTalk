import logging
from pathlib import Path

import requests
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import auth
from analysis import analyze_overlap
from github_client import (
    GitHubAuthError,
    fetch_readme,
    get_github_token,
    list_user_repositories,
    parse_repositories,
    search_github_repositories,
)

logger = logging.getLogger("crosstalk")
WEB_DIR = Path(__file__).parent / "web"

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
    "img-src 'self' data: https://avatars.githubusercontent.com; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith(("/api/", "/auth/")):
            response.headers["Cache-Control"] = "no-store"
        return response


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _current_session(request: Request) -> tuple[str | None, dict | None]:
    session_id = request.cookies.get(auth.SESSION_COOKIE)
    return session_id, auth.get_session(session_id)


def _token_for(session: dict | None) -> str | None:
    return session["token"] if session else get_github_token()


def _expired_response(session_id: str | None, signed_in: bool) -> JSONResponse:
    if signed_in:
        auth.end_session(session_id)
        response = _error("Your GitHub sign-in expired. Connect GitHub again.", 401)
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response
    return _error("GitHub rejected the configured GITHUB_TOKEN.", 502)


def _run_analysis(repository_names: list[str], token: str | None, allow_openai: bool) -> dict:
    repositories = {repo: fetch_readme(repo, token=token) for repo in repository_names}
    report = analyze_overlap(repositories, allow_openai=allow_openai)
    report["sources"] = repositories
    return report


async def search(request: Request) -> JSONResponse:
    session_id, session = _current_session(request)
    query = request.query_params.get("q", "")
    try:
        items = await run_in_threadpool(search_github_repositories, query, 10, _token_for(session))
        return JSONResponse(items)
    except GitHubAuthError:
        return _expired_response(session_id, session is not None)
    except ValueError as error:
        return _error(str(error), 400)
    except requests.RequestException as error:
        logger.warning("GitHub search failed: %s", error)
        return _error("Could not reach GitHub. Try again shortly.", 502)


async def analyze(request: Request) -> JSONResponse:
    session_id, session = _current_session(request)
    try:
        body = await request.json()
    except ValueError:
        return _error("Request body must be JSON.", 400)

    repositories = body.get("repositories") if isinstance(body, dict) else None
    if not isinstance(repositories, list) or not all(isinstance(item, str) for item in repositories):
        return _error('Send {"repositories": ["owner/repo", ...]}.', 400)

    try:
        repository_names = parse_repositories("\n".join(repositories))
        # Signed-in sessions can read private READMEs, so never send that text to OpenAI.
        report = await run_in_threadpool(_run_analysis, repository_names, _token_for(session), session is None)
        return JSONResponse(report)
    except GitHubAuthError:
        return _expired_response(session_id, session is not None)
    except ValueError as error:
        return _error(str(error), 400)
    except requests.RequestException as error:
        logger.warning("GitHub request failed: %s", error)
        return _error("Could not reach GitHub. Try again shortly.", 502)
    except Exception:
        logger.exception("Analysis failed")
        return _error("Analysis failed. Check the server log.", 500)


async def me(request: Request) -> JSONResponse:
    _, session = _current_session(request)
    body = {"configured": auth.is_configured(), "signed_in": session is not None}
    if session:
        body.update(login=session["login"], avatar_url=session["avatar_url"])
    return JSONResponse(body)


async def my_repos(request: Request) -> JSONResponse:
    session_id, session = _current_session(request)
    if session is None:
        return _error("Sign in with GitHub first.", 401)
    try:
        return JSONResponse(await run_in_threadpool(list_user_repositories, session["token"]))
    except GitHubAuthError:
        return _expired_response(session_id, True)
    except ValueError as error:
        return _error(str(error), 400)
    except requests.RequestException as error:
        logger.warning("GitHub repo listing failed: %s", error)
        return _error("Could not reach GitHub. Try again shortly.", 502)


async def auth_login(request: Request):
    if not auth.is_configured():
        return _error("GitHub sign-in isn't configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.", 503)
    return RedirectResponse(auth.begin_login(), status_code=302)


async def auth_callback(request: Request) -> RedirectResponse:
    if request.query_params.get("error"):
        return RedirectResponse("/?auth=denied", status_code=302)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return RedirectResponse("/?auth=failed", status_code=302)
    try:
        session_id = await run_in_threadpool(auth.complete_login, code, state)
    except auth.AuthError as error:
        logger.info("Sign-in failed: %s", error)
        return RedirectResponse("/?auth=failed", status_code=302)

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        auth.SESSION_COOKIE,
        session_id,
        max_age=auth.SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure(),
        path="/",
    )
    return response


async def auth_logout(request: Request) -> JSONResponse:
    auth.end_session(request.cookies.get(auth.SESSION_COOKIE))
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


app = Starlette(
    routes=[
        Route("/api/me", me, methods=["GET"]),
        Route("/api/my-repos", my_repos, methods=["GET"]),
        Route("/api/search", search, methods=["GET"]),
        Route("/api/analyze", analyze, methods=["POST"]),
        Route("/auth/login", auth_login, methods=["GET"]),
        Route("/auth/callback", auth_callback, methods=["GET"]),
        Route("/auth/logout", auth_logout, methods=["POST"]),
        Mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web"),
    ],
    middleware=[Middleware(SecurityHeaders)],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8600, reload=True)
