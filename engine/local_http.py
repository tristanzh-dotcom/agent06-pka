"""Bounded local control transport: no redirects or environment proxies."""
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, build_opener


def validate_loopback_url(value, *, base=True):
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"http", "https"}
                 and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                 and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment
                 and not any(char.isspace() or ord(char) < 32 for char in value)
                 and (not base or parsed.path in {"", "/"}))
        parsed.port  # Reject invalid ports before reading any credential.
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("approved loopback endpoint required")
    return value.rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_local_request(request, timeout, context=None):
    validate_loopback_url(request.full_url, base=False)
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))
    return opener.open(request, timeout=timeout)
