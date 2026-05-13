"""Client for fetching instrument schemas from the remote instr-registry."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests
import yaml

from .schema import InstrumentSchema

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://raw.githubusercontent.com/instr-community/instr-registry/main"


class RegistryClient:
    """Fetches instrument YAML schemas from a remote registry with local caching."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        timeout: float = 30,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        if cache_dir is None:
            cache_dir = Path.home() / ".instr-core" / "registry_cache"
        self._cache_dir = cache_dir
        self._timeout = timeout
        self._max_retries = max_retries

    @property
    def cache_dir(self) -> Path:
        """Return the local cache directory path."""
        return self._cache_dir

    def get_schema(self, vendor: str, type_: str, model: str) -> InstrumentSchema:
        """Return an instrument schema, fetching from remote if not cached locally.

        Args:
            vendor: Instrument manufacturer (e.g. ``keithley``).
            type_: Instrument category (e.g. ``smu``, ``dmm``).
            model: Instrument model number (e.g. ``2400``).
        """
        rel_path = f"{vendor.lower()}/{type_.lower()}/{model}.yaml"
        cache_path = self._cache_dir / rel_path

        if cache_path.exists():
            logger.debug("Cache hit for %s", rel_path)
            raw = cache_path.read_text(encoding="utf-8")
        else:
            logger.info("Fetching %s from remote registry", rel_path)
            raw = self._fetch(vendor, type_, model)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(raw, encoding="utf-8")

        data = yaml.safe_load(raw)
        return InstrumentSchema.model_validate(data)

    def _fetch(self, vendor: str, type_: str, model: str) -> str:
        url = f"{self._base_url}/registry/{vendor.lower()}/{type_.lower()}/{model}.yaml"
        last_exc: requests.RequestException | None = None
        for attempt in range(self._max_retries):
            try:
                response = requests.get(url, timeout=self._timeout)
                response.raise_for_status()
                return response.text
            except requests.HTTPError as exc:
                # Don't retry client errors (4xx), only server errors (5xx) and transient issues
                if exc.response is not None and exc.response.status_code < 500:
                    raise RuntimeError(f"Failed to fetch schema from {url}: {exc}") from exc
                last_exc = exc
                logger.warning(
                    "HTTP error fetching %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    self._max_retries,
                    exc,
                )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "Request error fetching %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    self._max_retries,
                    exc,
                )
            # Exponential backoff before retrying (1s, 2s, 4s, ...)
            if attempt < self._max_retries - 1:
                sleep_time = 2 ** attempt
                logger.debug("Retrying in %.1f seconds...", sleep_time)
                time.sleep(sleep_time)
        raise RuntimeError(
            f"Failed to fetch schema from {url} after {self._max_retries} attempts: {last_exc}"
        ) from last_exc
