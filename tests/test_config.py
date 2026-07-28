import os

import pytest


class TestGetDbPath:
    def test_default_path(self, monkeypatch):
        from src.config import get_db_path
        monkeypatch.delenv("DB_PATH", raising=False)
        assert get_db_path() == "data/leads.db"

    def test_env_var_overrides(self, monkeypatch):
        from src.config import get_db_path
        monkeypatch.setenv("DB_PATH", "/custom/path.db")
        assert get_db_path() == "/custom/path.db"


class TestLoadTargetsConfig:
    def test_returns_empty_list_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TARGETS_CONFIG", raising=False)
        from src.config import load_targets_config
        result = load_targets_config(path=str(tmp_path / "nonexistent.yml"))
        assert result == []

    def test_returns_empty_list_when_file_has_no_targets_key(self, tmp_path):
        config_file = tmp_path / "config.yml"
        config_file.write_text("other: data")
        from src.config import load_targets_config
        result = load_targets_config(path=str(config_file))
        assert result == []

    def test_returns_targets_list(self, tmp_path):
        config_file = tmp_path / "config.yml"
        config_file.write_text("targets:\n  - entry_url: https://a.com\n    parser: p1")
        from src.config import load_targets_config
        result = load_targets_config(path=str(config_file))
        assert result == [{"entry_url": "https://a.com", "parser": "p1"}]

    def test_returns_empty_when_targets_not_a_list(self, tmp_path):
        config_file = tmp_path / "config.yml"
        config_file.write_text("targets: not-a-list")
        from src.config import load_targets_config
        result = load_targets_config(path=str(config_file))
        assert result == []

    def test_returns_empty_when_yaml_is_not_dict(self, tmp_path):
        config_file = tmp_path / "config.yml"
        config_file.write_text("[1, 2, 3]")
        from src.config import load_targets_config
        result = load_targets_config(path=str(config_file))
        assert result == []

    def test_uses_env_var_path_when_no_path_given(self, monkeypatch, tmp_path):
        config_file = tmp_path / "custom.yml"
        config_file.write_text("targets: []")
        monkeypatch.setenv("TARGETS_CONFIG", str(config_file))
        from src.config import load_targets_config
        result = load_targets_config()
        assert result == []

    def test_warns_on_missing_file(self, capsys, tmp_path):
        from src.config import load_targets_config
        result = load_targets_config(path=str(tmp_path / "missing.yml"))
        assert result == []
        captured = capsys.readouterr()
        assert "WARNING" in (captured.out + captured.err)
