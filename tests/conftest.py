from __future__ import annotations

import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mockapi_yaml.app import MockApp


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Sleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.clock = Clock()
        self.sleeper = Sleeper()
        self.app: MockApp | None = None
        self.path = tmp_path / "mock.yaml"

    def write(self, text: str, name: str = "mock.yaml") -> Path:
        path = self.tmp_path / name
        path.write_text(textwrap.dedent(text), "utf-8")
        return path

    def client(self, text: str | None = None, **kwargs) -> TestClient:
        if text is not None:
            self.write(text)
        self.app = MockApp(self.path, sleep=self.sleeper, clock=self.clock, **kwargs)
        return TestClient(self.app)


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


@pytest.fixture
def mock(harness: Harness) -> Callable[..., TestClient]:
    return harness.client
