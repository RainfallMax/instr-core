"""Exclusive ownership for instrument addresses."""

from __future__ import annotations

import threading
from collections.abc import Iterable


class AddressOwnershipRegistry:
    """Track which active operation owns each instrument address."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._owners: dict[str, str] = {}

    def acquire(self, address: str, owner: str) -> bool:
        """Acquire one address, returning false when another owner holds it."""
        return self.acquire_many([address], owner)

    def acquire_many(self, addresses: Iterable[str], owner: str) -> bool:
        """Atomically acquire every address for one owner."""
        unique_addresses = tuple(dict.fromkeys(addresses))
        with self._lock:
            if any(
                address in self._owners and self._owners[address] != owner
                for address in unique_addresses
            ):
                return False
            for address in unique_addresses:
                self._owners[address] = owner
            return True

    def release(self, address: str, owner: str) -> bool:
        """Release one address only when it belongs to *owner*."""
        with self._lock:
            if self._owners.get(address) != owner:
                return False
            del self._owners[address]
            return True

    def release_many(self, addresses: Iterable[str], owner: str) -> None:
        """Release every address held by *owner* from the supplied set."""
        with self._lock:
            for address in tuple(dict.fromkeys(addresses)):
                if self._owners.get(address) == owner:
                    del self._owners[address]

    def snapshot(self) -> dict[str, str]:
        """Return an immutable-by-convention copy of current ownership."""
        with self._lock:
            return dict(self._owners)
