import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.routes import advisor, auth, campus, channels, core, experience, studio, workflow
from .config import get_settings
from .errors import (
    AppError,
    app_error_handler,
    generic_error_handler,
    http_error_handler,
    validation_error_handler,
)

# Resume and database files contain PII. Restrict newly created runtime files even
# when the service is launched outside the bundled development script.
if os.name == "posix":
    os.umask(0o077)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(Exception, generic_error_handler)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


app.include_router(auth.router)
app.include_router(auth.account_router)
app.include_router(core.router)
app.include_router(workflow.router)
app.include_router(channels.router)
app.include_router(campus.router)
app.include_router(experience.router)
app.include_router(studio.router)
app.include_router(advisor.router)
app.include_router(advisor.admin_router)
