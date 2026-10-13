"""Guarda la petición actual para que las señales sepan QUIÉN hizo un
movimiento de dinero y DESDE DÓNDE (mesa de vocalía o finanzas)."""
from contextvars import ContextVar

_request_actual = ContextVar('nexus_request_actual', default=None)


class RequestActualMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request_actual.set(request)
        try:
            return self.get_response(request)
        finally:
            _request_actual.reset(token)


def request_actual():
    return _request_actual.get()
