"""The id of the request being handled, so log lines and error messages can be matched up.

Set by `RequestContextMiddleware`. Background jobs have no request, so it is `None` there.
"""

from contextvars import ContextVar

REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return REQUEST_ID.get()
