"""Anchor URIs: immutable, SHA-pinned pointers to the text that made a claim (PRD §7.3).

    repo://<owner>/<repo>@<commit_sha>/<path>#L<start>-L<end>
    repo://<owner>/<repo>@<commit_sha>/<path>#sym=<qualname>
    wiki://<owner>/<repo>@<wiki_commit_sha>/<page>#L<start>-L<end>

An anchor pins a SHA specifically so provenance keeps pointing at the exact
text that produced an assertion even after the file changes -- resolving an
anchor to the file's *current* location of that text (if any) is a
presentation-layer concern for the exporters, not this module's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_ANCHOR_RE = re.compile(
    r"^(?P<scheme>repo|wiki)://(?P<owner>[^/]+)/(?P<repo>[^@]+)@(?P<sha>[0-9a-f]{7,40})"
    r"/(?P<path>[^#]+)#(?:L(?P<start>\d+)-L(?P<end>\d+)|sym=(?P<symbol>.+))$"
)


@dataclass(frozen=True, slots=True)
class Anchor:
    """A parsed anchor URI."""

    scheme: Literal["repo", "wiki"]
    owner: str
    repo: str
    commit_sha: str
    path: str
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None

    def to_uri(self) -> str:
        """Render back to the canonical anchor URI string."""
        base = f"{self.scheme}://{self.owner}/{self.repo}@{self.commit_sha}/{self.path}"
        if self.symbol is not None:
            return f"{base}#sym={self.symbol}"
        return f"{base}#L{self.line_start}-L{self.line_end}"


def parse(uri: str) -> Anchor:
    """Parse an anchor URI string.

    Raises:
        ValueError: `uri` doesn't match the anchor grammar.
    """
    match = _ANCHOR_RE.match(uri)
    if match is None:
        raise ValueError(f"not a valid anchor URI: {uri!r}")
    groups = match.groupdict()
    start = int(groups["start"]) if groups["start"] is not None else None
    end = int(groups["end"]) if groups["end"] is not None else None
    return Anchor(
        scheme=groups["scheme"],  # type: ignore[arg-type]
        owner=groups["owner"],
        repo=groups["repo"],
        commit_sha=groups["sha"],
        path=groups["path"],
        line_start=start,
        line_end=end,
        symbol=groups["symbol"],
    )
