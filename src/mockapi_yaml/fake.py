"""A tiny, dependency-free fake data generator for mock responses.

Every helper is a method of :class:`Fake` and is reachable from templates as
``{{faker.<name>}}`` or ``{{faker.<name>(arg, ...)}}``. The generator is seeded so
that a fixed ``settings.seed`` gives reproducible responses.
"""

from __future__ import annotations

import datetime as _dt
import random
import string
import uuid as _uuid
from collections.abc import Callable
from typing import Any

FIRST_NAMES = (
    "Ada", "Alan", "Amara", "Ana", "Arjun", "Aylin", "Ben", "Chen", "Chloe", "Dara", "Diego", "Elif", "Emma",
    "Farah", "Grace", "Hana", "Hugo", "Ines", "Ivan", "Jae", "Jonas", "Kai", "Kemal", "Lea", "Leo", "Lina",
    "Luca", "Maya", "Mei", "Mira", "Nia", "Noah", "Omar", "Priya", "Rafael", "Rosa", "Sami", "Sara", "Tariq",
    "Theo", "Uma", "Victor", "Yara", "Yusuf", "Zoe",
)  # fmt: skip
LAST_NAMES = (
    "Abbasi", "Andersen", "Bauer", "Costa", "Dubois", "Evans", "Fischer", "Garcia", "Haddad", "Ito", "Jensen",
    "Kim", "Kowalski", "Lopez", "Martin", "Meyer", "Nakamura", "Novak", "Okafor", "Patel", "Quinn", "Rahman",
    "Rossi", "Santos", "Schmidt", "Silva", "Tanaka", "Weber", "Wong", "Yilmaz", "Zhang",
)  # fmt: skip
WORDS = (
    "alpha", "amber", "anchor", "atlas", "beacon", "bloom", "bridge", "canvas", "cedar", "comet", "coral",
    "delta", "drift", "ember", "echo", "field", "forge", "glow", "harbor", "horizon", "island", "lantern",
    "maple", "meadow", "nova", "orbit", "pebble", "pixel", "quartz", "river", "signal", "spark", "stone",
    "summit", "tide", "timber", "vector", "willow", "zephyr",
)  # fmt: skip
CITIES = (
    "Amsterdam", "Austin", "Berlin", "Bogota", "Cairo", "Dhaka", "Dublin", "Istanbul", "Jakarta", "Kyoto",
    "Lagos", "Lisbon", "Madrid", "Melbourne", "Montreal", "Nairobi", "Oslo", "Prague", "Seoul", "Toronto",
)  # fmt: skip
COUNTRIES = (
    "Argentina", "Australia", "Bangladesh", "Brazil", "Canada", "Egypt", "France", "Germany", "India",
    "Indonesia", "Ireland", "Japan", "Kenya", "Mexico", "Netherlands", "Nigeria", "Norway", "Portugal",
    "South Korea", "Spain", "Turkey", "United Kingdom", "United States",
)  # fmt: skip
STREETS = ("Main St", "Oak Ave", "Park Rd", "Station Rd", "High St", "Elm St", "Lake View", "Mill Lane")
COMPANY_SUFFIX = ("Labs", "Systems", "Studio", "Works", "Group", "Collective", "Industries", "Co")
DOMAINS = ("example.com", "example.org", "example.net")
COLORS = ("red", "orange", "yellow", "green", "teal", "blue", "indigo", "violet", "pink", "gray")


class Fake:
    """Seedable fake data helpers. Public methods are exposed to templates."""

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def reseed(self, seed: int | None) -> None:
        self.rng.seed(seed)

    # -- people -------------------------------------------------------------
    def first_name(self) -> str:
        return self.rng.choice(FIRST_NAMES)

    def last_name(self) -> str:
        return self.rng.choice(LAST_NAMES)

    def name(self) -> str:
        return f"{self.first_name()} {self.last_name()}"

    def username(self) -> str:
        return f"{self.first_name().lower()}{self.rng.randint(1, 999)}"

    def email(self, domain: str | None = None) -> str:
        user = f"{self.first_name().lower()}.{self.last_name().lower()}{self.rng.randint(1, 99)}"
        return f"{user}@{domain or self.rng.choice(DOMAINS)}"

    def phone(self) -> str:
        return f"+1-555-{self.rng.randint(100, 999)}-{self.rng.randint(1000, 9999)}"

    def company(self) -> str:
        return f"{self.word().capitalize()} {self.rng.choice(COMPANY_SUFFIX)}"

    def job_title(self) -> str:
        level = self.rng.choice(("Junior", "Senior", "Lead", "Principal", ""))
        role = self.rng.choice(("Engineer", "Designer", "Product Manager", "Analyst", "Writer", "Researcher"))
        return f"{level} {role}".strip()

    # -- places -------------------------------------------------------------
    def city(self) -> str:
        return self.rng.choice(CITIES)

    def country(self) -> str:
        return self.rng.choice(COUNTRIES)

    def street_address(self) -> str:
        return f"{self.rng.randint(1, 9999)} {self.rng.choice(STREETS)}"

    def zip(self) -> str:
        return f"{self.rng.randint(0, 99999):05d}"

    def latitude(self) -> float:
        return round(self.rng.uniform(-90, 90), 6)

    def longitude(self) -> float:
        return round(self.rng.uniform(-180, 180), 6)

    # -- text ---------------------------------------------------------------
    def word(self) -> str:
        return self.rng.choice(WORDS)

    def words(self, count: int = 3) -> str:
        return " ".join(self.word() for _ in range(int(count)))

    def sentence(self, words: int = 8) -> str:
        return self.words(words).capitalize() + "."

    def paragraph(self, sentences: int = 3) -> str:
        return " ".join(self.sentence(self.rng.randint(5, 12)) for _ in range(int(sentences)))

    def slug(self, words: int = 3) -> str:
        return "-".join(self.word() for _ in range(int(words)))

    def string(self, length: int = 12) -> str:
        return "".join(self.rng.choice(string.ascii_letters + string.digits) for _ in range(int(length)))

    # -- numbers ------------------------------------------------------------
    def int(self, low: int = 0, high: int = 1000) -> int:
        return self.rng.randint(int(low), int(high))

    def float(self, low: float = 0, high: float = 1, digits: int = 2) -> float:
        return round(self.rng.uniform(float(low), float(high)), int(digits))

    def price(self, low: float = 1, high: float = 500) -> float:
        return self.float(low, high, 2)

    def bool(self, chance: float = 0.5) -> bool:
        return self.rng.random() < float(chance)

    def pick(self, *options: Any) -> Any:
        return self.rng.choice(options) if options else None

    # -- identifiers --------------------------------------------------------
    def uuid(self) -> str:
        return str(_uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def hex(self, length: int = 16) -> str:
        return "".join(self.rng.choice("0123456789abcdef") for _ in range(int(length)))

    def color(self) -> str:
        return self.rng.choice(COLORS)

    def hex_color(self) -> str:
        return f"#{self.rng.getrandbits(24):06x}"

    def ipv4(self) -> str:
        # Documentation ranges only (RFC 5737), so mock data never points at real hosts.
        prefix = self.rng.choice(("192.0.2", "198.51.100", "203.0.113"))
        return f"{prefix}.{self.rng.randint(1, 254)}"

    def url(self) -> str:
        return f"https://{self.rng.choice(DOMAINS)}/{self.slug(2)}"

    def image_url(self, width: int = 640, height: int = 480) -> str:
        return f"https://{self.rng.choice(DOMAINS)}/images/{self.hex(8)}-{int(width)}x{int(height)}.jpg"

    # -- dates --------------------------------------------------------------
    def date(self, days: int = 365) -> str:
        delta = _dt.timedelta(days=self.rng.randint(-int(days), int(days)))
        return (_dt.date.today() + delta).isoformat()

    def past_date(self, days: int = 365) -> str:
        return (_dt.date.today() - _dt.timedelta(days=self.rng.randint(1, int(days)))).isoformat()

    def future_date(self, days: int = 365) -> str:
        return (_dt.date.today() + _dt.timedelta(days=self.rng.randint(1, int(days)))).isoformat()

    def datetime(self, days: int = 365) -> str:
        seconds = self.rng.randint(-int(days) * 86400, int(days) * 86400)
        moment = _dt.datetime.now(_dt.UTC).replace(microsecond=0) + _dt.timedelta(seconds=seconds)
        return moment.isoformat().replace("+00:00", "Z")


HELPERS: tuple[str, ...] = tuple(
    name for name, value in vars(Fake).items() if not name.startswith("_") and callable(value) and name != "reseed"
)


def helper(fake: Fake, name: str) -> Callable[..., Any] | None:
    if name not in HELPERS:
        return None
    return getattr(fake, name)
