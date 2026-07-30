import logging
import re
from typing import Optional

from providers.base import TrailerProvider, TrailerPosition

logger = logging.getLogger(__name__)

PREFIX_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^EJGZ", re.I), "phillips"),
    (re.compile(r"^7328\d+$"), "fus1on"),
    (re.compile(r"\d+PLA$", re.I), "fus1on"),
    (re.compile(r"^SS\d", re.I), "skybitz"),
    (re.compile(r"^TL\d", re.I), "skybitz"),
    (re.compile(r"^53R\d", re.I), "skybitz"),
    (re.compile(r"^\d{5,6}$"), "skybitz"),
]


class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, TrailerProvider] = {}

    def register(self, provider: TrailerProvider) -> None:
        self._providers[provider.provider_name()] = provider

    def get_provider(self, name: str) -> Optional[TrailerProvider]:
        return self._providers.get(name)

    def get_provider_for_trailer(self, trailer_id: str) -> Optional[str]:
        for pattern, provider_name in PREFIX_RULES:
            if pattern.search(trailer_id):
                return provider_name
        return None

    async def get_all_positions(self) -> list[TrailerPosition]:
        all_positions: list[TrailerPosition] = []
        for name, provider in self._providers.items():
            try:
                positions = await provider.fetch_positions()
                for pos in positions:
                    pos.provider_name = name
                all_positions.extend(positions)
            except Exception as e:
                logger.error("Provider %s failed: %s", name, e)
        return all_positions
