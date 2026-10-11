from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Protocol

from starlette.requests import Request


class IPNetwork(Protocol):
    def __contains__(self, address: object) -> bool: ...


def resolve_client_ip(
    request: Request,
    trusted_proxy_networks: tuple[IPNetwork, ...],
) -> str:
    peer = request.client.host if request.client else "unknown"
    peer_address = _parse_address(peer)
    if peer_address is None or not _is_trusted(
        peer_address,
        trusted_proxy_networks,
    ):
        return peer

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return peer

    forwarded_addresses: list[IPv4Address | IPv6Address] = []
    for entry in forwarded_for.split(","):
        address = _parse_address(entry.strip())
        if address is None:
            return peer
        forwarded_addresses.append(address)

    for address in reversed(forwarded_addresses):
        if not _is_trusted(address, trusted_proxy_networks):
            return str(address)

    return str(forwarded_addresses[0]) if forwarded_addresses else peer


def _parse_address(value: str) -> IPv4Address | IPv6Address | None:
    try:
        return ip_address(value)
    except ValueError:
        return None


def _is_trusted(
    address: IPv4Address | IPv6Address,
    networks: tuple[IPNetwork, ...],
) -> bool:
    return any(address in network for network in networks)
