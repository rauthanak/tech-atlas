"""Where the radar may read: public websites only. A link, or a redirect,
to an address inside a private network (this server, the office network, the
cloud's own metadata address) is refused before it is fetched, by the crawler,
by Find evidence and by a pasted link alike."""

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

PRIVATE = "its address is inside a private network: the radar reads only public websites"


class NotPublic(httpx.RequestError):
    """A fetch refused because its address isn't public."""


def private_host(url: str) -> str | None:
    """The host, when it is or resolves to an address that isn't public
    (loopback, private, link-local, shared, reserved, multicast); else None.
    A host that doesn't resolve is left to fail as any unreachable site does."""
    host = urlsplit(url).hostname
    if not host:
        return None
    try:
        found = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return None
    for *_, address in found:
        ip = ipaddress.ip_address(address[0].split("%")[0])
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if not ip.is_global or ip.is_multicast:
            return host
    return None


def refuse_private(request: httpx.Request) -> None:
    """An httpx request hook: it runs before the first request and before every redirect."""
    if private_host(str(request.url)):
        raise NotPublic(PRIVATE, request=request)


PUBLIC_ONLY = {"request": [refuse_private]}
