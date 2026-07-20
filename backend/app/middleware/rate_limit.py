"""Rate-limiting middleware powered by slowapi.

Configures a global :class:`slowapi.Limiter` keyed on the authenticated
principal when available, otherwise on the first forwarded client IP or the
socket peer. Individual route limits are applied via decorators in the
respective router modules.
"""

from ipaddress import ip_address

from fastapi import Request
from slowapi import Limiter


def _first_forwarded_ip(raw_header: str | None) -> str | None:
    if not raw_header:
        return None

    for candidate in raw_header.split(","):
        value = candidate.strip()
        if not value:
            continue
        try:
            ip_address(value)
        except ValueError:
            continue
        return value
    return None


def get_rate_limit_key(request: Request) -> str:
    principal = getattr(request.state, "user", None)
    subject_id = getattr(principal, "subject_id", None)
    if subject_id:
        return f"user:{subject_id}"

    forwarded_ip = _first_forwarded_ip(request.headers.get("x-forwarded-for"))
    if forwarded_ip:
        return f"ip:{forwarded_ip}"

    client_host = request.client.host if request.client else None
    return f"ip:{client_host or '127.0.0.1'}"


def get_auth_client_ip(request: Request) -> str:
    """Resolve an auth-attempt IP without trusting user-supplied X-Forwarded-For.

    Accord's nginx accepts traffic only from trusted local/tunnel peers and
    replaces ``X-Forwarded-For`` with one validated client address. Accept that
    single proxy-owned value only from a private/loopback peer. Do not trust
    ``CF-Connecting-IP`` here because nginx does not rewrite that header.
    """
    peer = request.client.host if request.client else "127.0.0.1"
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return peer

    if peer_ip.is_private or peer_ip.is_loopback:
        candidate = request.headers.get("x-forwarded-for")
        if candidate and "," not in candidate:
            try:
                return str(ip_address(candidate.strip()))
            except ValueError:
                pass
    return str(peer_ip)


def get_auth_rate_limit_key(request: Request) -> str:
    return f"auth-ip:{get_auth_client_ip(request)}"


limiter = Limiter(key_func=get_rate_limit_key)
