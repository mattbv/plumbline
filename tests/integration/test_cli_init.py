"""`plumb init` end to end, against a real Ontolith-backed knowledge base
(no fakes) -- this is the one thing the M0 scaffold promises actually works."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from plumbline.interfaces.cli import app

pytestmark = pytest.mark.integration

runner = CliRunner()


class TestInit:
    def test_creates_config_and_kb_file(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["init", "--admin", "alice@example.com", "--path", str(tmp_path)]
        )

        assert result.exit_code == 0, result.output
        assert (tmp_path / "plumbline.toml").exists()
        assert (tmp_path / ".plumbline" / "kb.db").exists()

    def test_refuses_to_overwrite_an_existing_config(self, tmp_path: Path) -> None:
        runner.invoke(app, ["init", "--admin", "alice@example.com", "--path", str(tmp_path)])

        result = runner.invoke(app, ["init", "--admin", "bob@example.com", "--path", str(tmp_path)])

        assert result.exit_code == 1

    def test_config_records_the_admin_principal(self, tmp_path: Path) -> None:
        runner.invoke(app, ["init", "--admin", "alice@example.com", "--path", str(tmp_path)])

        config_text = (tmp_path / "plumbline.toml").read_text()

        assert 'admin = "alice@example.com"' in config_text


class TestVersion:
    def test_version_flag_prints_and_exits_cleanly(self) -> None:
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "plumb" in result.output
