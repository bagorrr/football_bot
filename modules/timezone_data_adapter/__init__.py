"""Installed, source-bound IANA timezone-data adapter."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import IO, Protocol
from zoneinfo import TZPATH, ZoneInfo

from modules.ports import ResolvedTimezoneData, TimezoneDataError


class TimezoneDataSource(Protocol):
    """One ordered timezone-data source boundary."""

    def load_timezone(self, iana_timezone: str) -> ZoneInfo | None:
        """Load a zone from this source, or return ``None`` when absent."""
        ...

    def load_version(self) -> str | None:
        """Return this source's exact tzdb version when verifiable."""
        ...


class SourceBoundTimezoneDataAdapter:
    """Resolve a zone and version from the first source containing that zone."""

    def __init__(self, sources: tuple[TimezoneDataSource, ...]) -> None:
        self._sources = sources

    def resolve(self, iana_timezone: str) -> ResolvedTimezoneData:
        """Resolve from one source and fail closed when its version is unknown."""
        for source in self._sources:
            timezone = source.load_timezone(iana_timezone)
            if timezone is None:
                continue
            version = source.load_version()
            if version is None or re.fullmatch(r"\S+", version) is None:
                raise TimezoneDataError(
                    "timezone source has no verifiable database version"
                )
            return ResolvedTimezoneData(
                iana_timezone=iana_timezone,
                timezone=timezone,
                version=version,
            )
        raise TimezoneDataError("timezone is absent from installed data")


class InstalledTimezoneDataAdapter(SourceBoundTimezoneDataAdapter):
    """Use Python's ordered ``TZPATH`` roots and ``tzdata`` package fallback."""

    def __init__(self) -> None:
        sources: tuple[TimezoneDataSource, ...] = (
            *(_FilesystemTimezoneDataSource(Path(root)) for root in TZPATH),
            _PackageTimezoneDataSource(),
        )
        super().__init__(sources)


class _FilesystemTimezoneDataSource:
    def __init__(self, root: Path) -> None:
        self._root = root

    def load_timezone(self, iana_timezone: str) -> ZoneInfo | None:
        path = self._root.joinpath(*_timezone_components(iana_timezone))
        try:
            with path.open("rb") as zone_file:
                return _zoneinfo_from_file(zone_file, iana_timezone)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise TimezoneDataError("timezone source could not be read") from error

    def load_version(self) -> str | None:
        try:
            with (self._root / "tzdata.zi").open(encoding="utf-8") as version_file:
                return _parse_version(version_file.readline())
        except OSError:
            return None


class _PackageTimezoneDataSource:
    def _root(self) -> resources.abc.Traversable | None:
        try:
            return resources.files("tzdata.zoneinfo")
        except ModuleNotFoundError:
            return None

    def load_timezone(self, iana_timezone: str) -> ZoneInfo | None:
        root = self._root()
        if root is None:
            return None
        resource = root.joinpath(*_timezone_components(iana_timezone))
        try:
            with resource.open("rb") as zone_file:
                return _zoneinfo_from_file(zone_file, iana_timezone)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise TimezoneDataError("tzdata package zone could not be read") from error

    def load_version(self) -> str | None:
        root = self._root()
        if root is None:
            return None
        try:
            with root.joinpath("tzdata.zi").open(encoding="utf-8") as version_file:
                return _parse_version(version_file.readline())
        except OSError:
            return None


def _timezone_components(iana_timezone: str) -> tuple[str, ...]:
    path = PurePosixPath(iana_timezone)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise TimezoneDataError("invalid IANA timezone identifier")
    return path.parts


def _zoneinfo_from_file(zone_file: IO[bytes], iana_timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo.from_file(zone_file, key=iana_timezone)
    except ValueError as error:
        raise TimezoneDataError("timezone source contains invalid data") from error


def _parse_version(first_line: str) -> str | None:
    match = re.fullmatch(r"# version (\S+)\n?", first_line)
    return match.group(1) if match is not None else None
