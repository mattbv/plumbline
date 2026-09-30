"""Anchor URIs are provenance you can click -- parsing must round-trip
exactly, since an anchor is meant to keep pointing at the precise text that
made a claim (PRD §7.3)."""

from __future__ import annotations

import pytest

from plumbline.domain import anchors


class TestParseRepoLineRange:
    def test_parses_all_fields(self) -> None:
        anchor = anchors.parse("repo://acme/sdk@9f3e1c2/README.md#L88-L91")
        assert anchor.scheme == "repo"
        assert anchor.owner == "acme"
        assert anchor.repo == "sdk"
        assert anchor.commit_sha == "9f3e1c2"
        assert anchor.path == "README.md"
        assert anchor.line_start == 88
        assert anchor.line_end == 91
        assert anchor.symbol is None

    def test_round_trips_to_the_same_uri(self) -> None:
        uri = "repo://acme/sdk@9f3e1c2/README.md#L88-L91"
        assert anchors.parse(uri).to_uri() == uri


class TestParseSymbolAnchor:
    def test_parses_symbol_form(self) -> None:
        anchor = anchors.parse("repo://acme/sdk@9f3e1c2/src/client.py#sym=acme.Client.connect")
        assert anchor.symbol == "acme.Client.connect"
        assert anchor.line_start is None

    def test_round_trips(self) -> None:
        uri = "repo://acme/sdk@9f3e1c2/src/client.py#sym=acme.Client.connect"
        assert anchors.parse(uri).to_uri() == uri


class TestParseWikiAnchor:
    def test_wiki_scheme(self) -> None:
        anchor = anchors.parse("wiki://acme/sdk@abc1234/Tuning#L1-L5")
        assert anchor.scheme == "wiki"


class TestInvalidAnchors:
    @pytest.mark.parametrize(
        "bad_uri",
        [
            "not-a-uri-at-all",
            "https://github.com/acme/sdk/blob/main/README.md",  # not the anchor grammar
            "repo://acme/sdk/README.md#L1-L2",  # missing commit sha
        ],
    )
    def test_raises_value_error(self, bad_uri: str) -> None:
        with pytest.raises(ValueError, match="not a valid anchor URI"):
            anchors.parse(bad_uri)
