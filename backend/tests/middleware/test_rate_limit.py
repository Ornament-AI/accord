from starlette.requests import Request

from app.auth.principal import AuthPrincipal
from app.middleware.rate_limit import (
    _first_forwarded_ip,
    get_auth_client_ip,
    get_auth_rate_limit_key,
    get_rate_limit_key,
)


def _build_request(
    *,
    forwarded_for: str | None = None,
    cloudflare_ip: str | None = None,
    client_host: str = "10.0.0.5",
    principal: AuthPrincipal | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    if cloudflare_ip is not None:
        headers.append((b"cf-connecting-ip", cloudflare_ip.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/healthz",
        "headers": headers,
        "client": (client_host, 12345),
        "state": {},
    }
    request = Request(scope)
    if principal is not None:
        request.state.user = principal
    return request


def test_first_forwarded_ip_returns_first_valid_ip() -> None:
    assert _first_forwarded_ip("203.0.113.9, 10.0.0.2") == "203.0.113.9"


def test_first_forwarded_ip_skips_invalid_entries() -> None:
    assert _first_forwarded_ip("garbage, 198.51.100.7") == "198.51.100.7"


def test_rate_limit_key_prefers_authenticated_principal() -> None:
    principal = AuthPrincipal(
        user_id="00000000-0000-4000-8000-000000000042",
        subject_id="uid-42",
        email="admin@accord.local",
        role="organization_administrator",
        is_active=True,
    )
    request = _build_request(
        forwarded_for="203.0.113.9",
        client_host="172.18.0.4",
        principal=principal,
    )

    assert get_rate_limit_key(request) == "user:uid-42"


def test_rate_limit_key_falls_back_to_forwarded_ip() -> None:
    request = _build_request(forwarded_for="203.0.113.9, 172.18.0.4", client_host="172.18.0.4")

    assert get_rate_limit_key(request) == "ip:203.0.113.9"


def test_rate_limit_key_falls_back_to_socket_peer_when_no_forwarded_ip() -> None:
    request = _build_request(client_host="172.18.0.4")

    assert get_rate_limit_key(request) == "ip:172.18.0.4"


def test_auth_rate_limit_ignores_forwarded_for_from_public_peer() -> None:
    request = _build_request(
        client_host="8.8.8.8",
        forwarded_for="1.1.1.1",
    )

    assert get_auth_client_ip(request) == "8.8.8.8"
    assert get_auth_rate_limit_key(request) == "auth-ip:8.8.8.8"


def test_auth_rate_limit_ignores_unsanitized_cloudflare_header() -> None:
    proxied = _build_request(
        client_host="172.18.0.4",
        cloudflare_ip="1.1.1.1",
    )
    direct = _build_request(
        client_host="8.8.8.8",
        cloudflare_ip="1.1.1.1",
    )

    assert get_auth_client_ip(proxied) == "172.18.0.4"
    assert get_auth_client_ip(direct) == "8.8.8.8"


def test_auth_rate_limit_accepts_nginx_sanitized_forwarded_ip() -> None:
    request = _build_request(
        client_host="172.18.0.4",
        forwarded_for="1.1.1.1",
    )
    unsanitized_chain = _build_request(
        client_host="172.18.0.4",
        forwarded_for="1.1.1.1, 8.8.8.8",
    )

    assert get_auth_client_ip(request) == "1.1.1.1"
    assert get_auth_client_ip(unsanitized_chain) == "172.18.0.4"
