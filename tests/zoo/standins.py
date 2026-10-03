"""Label-driven stand-ins for the doc importers that do not exist yet.

Plumbline has a real docstring importer; it has no README, docs, or CHANGELOG importers.
So that the *rest* of the pipeline -- the projector, the four-pass ordering, and
Ontolith's static routing -- can be checked against every scenario now, this importer
emits exactly the claims the zoo's own labels state for one principal.

It is a test double, deliberately transparent: it does not parse Markdown. What it
verifies is everything downstream of a claim. Whether a future real importer extracts
the same claims is that importer's own test, against these same labels.
"""

from __future__ import annotations

from plumbline.application.ports import CommitRef, DocExtraction, RawClaim
from plumbline.domain.projection import is_projectable

from .importing import ZooHistory
from .model import Scenario


def _doc_path(principal: str, scenario: Scenario, label: str) -> str:
    base = f"scenarios/{scenario.id}/"
    if principal == "plumb-readme":
        return f"{base}README.md"
    if principal == "plumb-changelog":
        return f"{base}CHANGELOG.md"
    pages = sorted(
        p for p in scenario.files_at(label) if p.startswith("docs/") and p.endswith(".md")
    )
    return f"{base}{pages[0] if pages else 'docs/guide.md'}"


class LabeledClaimImporter:
    """Claims for ``principal`` exactly as the scenario's labels state them.

    Labels are carried forward from the commit they are stated at, and a slot whose first
    label comes after the document was written is backfilled to the start (the document is
    taken to have said then what it is first labeled as saying).
    """

    def __init__(self, principal: str, history: ZooHistory) -> None:
        self.principal = principal
        self._history = history

    def handles(self, path: str) -> bool:
        """The documents this principal owns: its README, CHANGELOG, or docs pages."""
        name = path.rsplit("/", 1)[-1]
        if self.principal == "plumb-readme":
            return name == "README.md"
        if self.principal == "plumb-changelog":
            return name == "CHANGELOG.md"
        return "/docs/" in f"/{path}" and path.endswith(".md")

    def extract(self, files: dict[str, bytes], commit: CommitRef) -> DocExtraction:
        """The labeled claims as of this commit, for the paths changed in it."""
        scenario, label = self._history.at(commit.sha)
        index = scenario.commit_index(label)
        latest: dict[tuple[str, str], str] = {}
        seen: set[tuple[str, str]] = set()
        labeled = [
            e
            for e in scenario.expectations
            if e.symbol.startswith("py:") and is_projectable(e.aspect)
        ]
        # Carry each label forward from the commit it is stated at...
        for exp in sorted(labeled, key=lambda e: scenario.commit_index(e.commit)):
            if scenario.commit_index(exp.commit) > index:
                continue
            key = (exp.symbol, exp.aspect)
            seen.add(key)
            values = [v for p, v in exp.claims if p == self.principal]
            if values:
                latest[key] = values[0]
            else:
                latest.pop(key, None)  # a later label says this principal no longer states it
        # ...and backfill a slot whose first label comes later: a document unchanged since it
        # was written states then what it is first labeled as stating.
        for exp in sorted(labeled, key=lambda e: scenario.commit_index(e.commit), reverse=True):
            key = (exp.symbol, exp.aspect)
            values = [v for p, v in exp.claims if p == self.principal]
            if key not in seen and values:
                latest[key] = values[0]
        path = _doc_path(self.principal, scenario, label)
        exists = path.removeprefix(f"scenarios/{scenario.id}/") in scenario.files_at(label)
        claims = [
            RawClaim(
                symbol,
                aspect,
                value,
                f"repo://zoo/zoo@{commit.sha}/{path}#L1-L1",
                0.9,
                "label-driven stand-in",
            )
            for (symbol, aspect), value in sorted(latest.items())
            if exists
        ]
        analyzed = frozenset(p for p in files if self.handles(p))
        return DocExtraction(claims, analyzed)
