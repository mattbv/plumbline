from __future__ import annotations

import pytest

from plumbline.domain import aspects


class TestCatalog:
    def test_get_returns_known_aspect(self) -> None:
        aspect = aspects.get("exists")
        assert aspect.name == "exists"
        assert aspect.drift_capable is True

    def test_get_raises_for_unknown_aspect(self) -> None:
        with pytest.raises(KeyError):
            aspects.get("not-a-real-aspect")

    def test_raises_aspect_is_corroboration_only(self) -> None:
        """`raises.<Exc>` can prove presence but never absence -- it must be
        marked not drift-capable, or a doc claiming an exception that isn't
        raised would falsely count as verified drift (PRD §7.4, Worked
        Example table's own "corroboration only" note)."""
        aspect = aspects.get("raises.<Exc>")
        assert aspect.drift_capable is False

    def test_catalog_names_are_unique(self) -> None:
        names = [aspect.name for aspect in aspects.CATALOG]
        assert len(names) == len(set(names))
