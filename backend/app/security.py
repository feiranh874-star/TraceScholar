"""Single-process demo guard, applied before multipart body parsing."""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
import time
from collections import deque
from urllib.parse import urlsplit

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings


class DemoGuardMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.upload_times: deque[float] = deque()
        self.failed_login_times: deque[float] = deque()
        self.active_uploads = 0

    @staticmethod
    def _trim(window: deque[float], now: float) -> None:
        while window and window[0] <= now - 60:
            window.popleft()

    def _authorized(self, value: str) -> bool:
        try:
            scheme, token = value.split(" ", 1)
            if scheme.lower() != "basic":
                return False
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return False
        # Fixed-size digests also permit non-ASCII credentials.
        username_ok = secrets.compare_digest(
            hashlib.sha256(username.encode()).digest(),
            hashlib.sha256(self.settings.demo_username.encode()).digest(),
        )
        password_ok = secrets.compare_digest(
            hashlib.sha256(password.encode()).digest(),
            hashlib.sha256(self.settings.demo_password.encode()).digest(),
        )
        return username_ok and password_ok

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        headers = {key.lower(): value for key, value in scope.get("headers", [])}

        # Host health probes contain no user data and do not need credentials.
        public_health = path == "/health" and scope["method"] in {"GET", "HEAD"}
        if self.settings.demo_password and not public_health:
            auth = headers.get(b"authorization", b"").decode("latin-1")
            if not self._authorized(auth):
                now = time.monotonic()
                self._trim(self.failed_login_times, now)
                if len(self.failed_login_times) >= 60:
                    response = JSONResponse(
                        {"detail": "登录尝试过多，请一分钟后重试。"},
                        status_code=429, headers={"Retry-After": "60"},
                    )
                else:
                    self.failed_login_times.append(now)
                    response = JSONResponse(
                        {"detail": "请输入演示账号和密码。"}, status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="TraceScholar", charset="UTF-8"'},
                    )
                await response(scope, receive, send)
                return

        if self.settings.demo_password and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get(b"origin", b"").decode("latin-1")
            host = headers.get(b"host", b"").decode("latin-1")
            fetch_site = headers.get(b"sec-fetch-site", b"").lower()
            try:
                origin_parts = urlsplit(origin)
                invalid_origin = bool(origin) and (
                    origin_parts.scheme not in {"http", "https"}
                    or origin_parts.netloc.lower() != host.lower()
                )
            except ValueError:
                invalid_origin = True
            if invalid_origin or fetch_site == b"cross-site":
                await JSONResponse(
                    {"detail": "不允许从其他网站提交文件，请在本站操作。"}, status_code=403,
                )(scope, receive, send)
                return

        declared_length = headers.get(b"content-length")
        if declared_length is not None:
            try:
                length = int(declared_length)
                if length < 0:
                    raise ValueError
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
                return
            if length > self.settings.max_request_bytes:
                await JSONResponse({"detail": "请求体超过大小限制。"}, status_code=413)(scope, receive, send)
                return

        is_upload = (path.rstrip("/") in {"/api/papers", "/api/library/import", "/api/library/batch-upload"}) and scope["method"] == "POST"
        if is_upload:
            now = time.monotonic()
            self._trim(self.upload_times, now)
            limit = self.settings.upload_requests_per_minute
            rate_exceeded = bool(limit and len(self.upload_times) >= limit)
            if rate_exceeded or self.active_uploads >= self.settings.max_concurrent_uploads:
                await JSONResponse(
                    {"detail": "上传过于频繁或服务正在处理其他文件，请稍后重试。"},
                    status_code=429, headers={"Retry-After": "60"},
                )(scope, receive, send)
                return
            if limit:
                self.upload_times.append(now)
            self.active_uploads += 1

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.settings.max_request_bytes:
                    raise HTTPException(status_code=413, detail="请求体超过大小限制。")
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                response_headers = list(message.get("headers", []))
                response_headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"SAMEORIGIN" if path.endswith("/source.pdf") else b"DENY"),
                    (b"referrer-policy", b"same-origin"),
                ])
                if self.settings.demo_password:
                    response_headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except HTTPException as error:
            if response_started:
                raise
            await JSONResponse({"detail": error.detail}, status_code=error.status_code)(scope, receive, send)
        finally:
            if is_upload:
                self.active_uploads -= 1
