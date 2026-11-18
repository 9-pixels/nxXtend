# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 9-pixels


class PackageSearchError(Exception):
    """One package channel could not be searched.

    ``source`` names the channel (``"stable"`` / ``"unstable"``) and
    ``reason`` is a user-readable explanation. The underlying exception is
    chained for debugging; it is never shown to the user as a traceback.
    """

    def __init__(self, source: str, reason: str):
        super().__init__(f"could not search {source}: {reason}")
        self.source = source
        self.reason = reason


class PackageSearchFailed(Exception):
    """Aggregated search failure.

    Raised by the search layer when a channel could not be searched, so the
    caller learns that the results it holds are incomplete instead of
    silently proceeding with a partial set.
    """

    def __init__(self, errors: "list[PackageSearchError]"):
        self.errors = list(errors)
        super().__init__("; ".join(str(error) for error in self.errors))

    @property
    def detail(self) -> str:
        """One line per failed channel, ready to hand to the display layer."""
        return "\n".join(
            f"  could not search {error.source}: {error.reason}"
            for error in self.errors
        )
