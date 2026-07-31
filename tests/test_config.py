import os
from pathlib import Path

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


class TestLoadFullConfigDefaultPath:
    def test_defaults_to_targets_yaml(self, monkeypatch):
        """T001 — default path is config/targets.yaml (renamed file)."""
        monkeypatch.delenv("TARGETS_CONFIG", raising=False)
        import inspect
        from src.config import load_full_config
        src = inspect.getsource(load_full_config)
        assert '"config/targets.yaml"' in src


class TestIcpGettersTopLevel:
    """T002 — ICP allowlists read the top-level icp_categories/icp_cities keys."""

    def test_icp_categories_top_level(self):
        from src.config import get_icp_categories
        cfg = {"icp_categories": ["software-development", "web-design"], "icp_cities": []}
        assert get_icp_categories(cfg) == {"software-development", "web-design"}

    def test_icp_cities_top_level(self):
        from src.config import get_icp_cities
        cfg = {"icp_categories": [], "icp_cities": ["new-delhi", "mumbai"]}
        assert get_icp_cities(cfg) == {"new-delhi", "mumbai"}

    def test_missing_keys_default_empty(self):
        from src.config import get_icp_categories, get_icp_cities
        assert get_icp_categories({}) == set()
        assert get_icp_cities({}) == set()

    def test_dict_items_support_dict_shape(self):
        from src.config import get_icp_categories
        cfg = {"icp_categories": [{"slug": "seo-services"}]}
        assert get_icp_categories(cfg) == {"seo-services"}


def _cats(n):
    return [
        {"slug": f"cat{i}", "labels": {"indiamart": f"cat-{i}", "tradeindia": f"cat{i}"}}
        for i in range(n)
    ]


def _cities(n):
    return [
        {
            "slug": f"city{i}",
            "labels": {"indiamart": f"city{i}", "tradeindia": f"city{i}"},
            "tradeindia_code": str(100000 + i),
        }
        for i in range(n)
    ]


TEMPLATES = {
    "indiamart": "https://dir.indiamart.com/{city}/{category}.html",
    "tradeindia": "https://www.tradeindia.com/{city}/{category}-city-{code}.html",
}


class TestExpandStartUrls:
    """T003 — cross-product expansion (FR-003, SC-001, spec User Story 1 Independent Test)."""

    def test_cross_product_counts(self):
        from src.scraper.targets import expand_start_urls
        combos = expand_start_urls(_cats(2), _cities(2), TEMPLATES)
        im = [c for c in combos if c.site == "indiamart"]
        ti = [c for c in combos if c.site == "tradeindia"]
        assert len(im) == 4
        assert len(ti) == 4

        big = expand_start_urls(_cats(10), _cities(10), TEMPLATES)
        assert len([c for c in big if c.site == "indiamart"]) == 100
        assert len([c for c in big if c.site == "tradeindia"]) == 100

    def test_growth_without_code_change(self):
        from src.scraper.targets import expand_start_urls
        small = expand_start_urls(_cats(2), _cities(3), TEMPLATES)
        big = expand_start_urls(_cats(4), _cities(6), TEMPLATES)
        assert len(small) == (2 * 3) * 2
        assert len(big) == (4 * 6) * 2

    def test_exact_starter_urls(self):
        from src.scraper.targets import expand_start_urls
        cats = [{"slug": "software-development", "labels": {
            "indiamart": "software-development-services", "tradeindia": "software-development",
        }}]
        cities = [{"slug": "new-delhi", "labels": {
            "indiamart": "new-delhi", "tradeindia": "new-delhi",
        }, "tradeindia_code": "228067"}]
        combos = expand_start_urls(cats, cities, TEMPLATES)
        urls = {c.site: c.url for c in combos}
        assert urls["indiamart"] == "https://dir.indiamart.com/new-delhi/software-development-services.html"
        assert urls["tradeindia"] == "https://www.tradeindia.com/new-delhi/software-development-city-228067.html"

    def test_bangalore_uses_bengaluru_label_and_code(self):
        from src.scraper.targets import expand_start_urls
        cities = [{"slug": "bangalore", "labels": {
            "indiamart": "bangalore", "tradeindia": "bengaluru",
        }, "tradeindia_code": "183339"}]
        combos = expand_start_urls(_cats(1), cities, TEMPLATES)
        ti = next(c for c in combos if c.site == "tradeindia")
        assert ti.url == "https://www.tradeindia.com/bengaluru/cat0-city-183339.html"
        assert "bangalore" not in ti.url

    def test_category_major_city_minor_order(self):
        from src.scraper.targets import expand_start_urls
        combos = expand_start_urls(_cats(2), _cities(2), TEMPLATES)
        im = [c for c in combos if c.site == "indiamart"]
        keys = [(c.category_slug, c.city_slug) for c in im]
        assert keys == [
            ("cat0", "city0"), ("cat0", "city1"),
            ("cat1", "city0"), ("cat1", "city1"),
        ]

    def test_empty_categories_warns_and_returns_empty(self, caplog):
        import logging
        from src.scraper.targets import expand_start_urls
        with caplog.at_level(logging.WARNING):
            combos = expand_start_urls([], _cities(2), TEMPLATES)
        assert combos == []
        assert "No categories or cities" in caplog.text

    def test_empty_cities_warns_and_returns_empty(self, caplog):
        import logging
        from src.scraper.targets import expand_start_urls
        with caplog.at_level(logging.WARNING):
            combos = expand_start_urls(_cats(2), [], TEMPLATES)
        assert combos == []

    def test_missing_category_label_skips_combo_with_warning(self, caplog):
        """A category with an empty label for a site is skipped for that site."""
        import logging
        from src.scraper.targets import expand_start_urls
        cats = [{"slug": "cat0", "labels": {"indiamart": "cat-0", "tradeindia": ""}}]
        with caplog.at_level(logging.WARNING):
            combos = expand_start_urls(cats, _cities(1), TEMPLATES)
        assert [c.site for c in combos] == ["indiamart"]
        assert len(combos) == 1
        assert "missing label" in caplog.text

    def test_missing_city_label_skips_combo_with_warning(self, caplog):
        """A city with an empty label for a site is skipped for that site."""
        import logging
        from src.scraper.targets import expand_start_urls
        cities = [{
            "slug": "city0",
            "labels": {"indiamart": "city0", "tradeindia": ""},
            "tradeindia_code": "100000",
        }]
        with caplog.at_level(logging.WARNING):
            combos = expand_start_urls(_cats(1), cities, TEMPLATES)
        assert [c.site for c in combos] == ["indiamart"]
        assert len(combos) == 1
        assert "missing label" in caplog.text

    def test_missing_tradeindia_code_fails_loudly(self):
        from src.scraper.targets import expand_start_urls
        cities = [{"slug": "pune", "labels": {"indiamart": "pune", "tradeindia": "pune"}}]
        with pytest.raises(ValueError, match="tradeindia_code"):
            expand_start_urls(_cats(1), cities, TEMPLATES)

    def test_sites_param_filters(self):
        from src.scraper.targets import expand_start_urls
        combos = expand_start_urls(_cats(2), _cities(2), TEMPLATES, sites=("indiamart",))
        assert {c.site for c in combos} == {"indiamart"}
        assert len(combos) == 4

    def test_deterministic_pure(self):
        from src.scraper.targets import expand_start_urls
        assert expand_start_urls(_cats(2), _cities(3), TEMPLATES) == \
            expand_start_urls(_cats(2), _cities(3), TEMPLATES)


class TestStarterFileContract:
    """FR-001 — the shipped config/targets.yaml is runnable without operator edits (Q1)."""

    CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "targets.yaml"

    def _config(self):
        from src.config import load_full_config
        return load_full_config(path=str(self.CONFIG_PATH))

    def test_starter_has_ten_categories_and_ten_cities(self):
        cfg = self._config()
        assert len(cfg["categories"]) == 10
        assert len(cfg["cities"]) == 10

    def test_starter_cities_all_carry_tradeindia_code(self):
        cfg = self._config()
        for city in cfg["cities"]:
            assert isinstance(city.get("tradeindia_code"), str)
            assert city["tradeindia_code"]

    def test_starter_enabled_im_ti_targets_have_valid_limits(self):
        cfg = self._config()
        by_name = {t["name"].lower(): t for t in cfg["targets"]}
        for name in ("indiamart", "tradeindia"):
            target = by_name[name]
            assert target["enabled"] is True
            assert isinstance(target.get("max_pages"), int) and target["max_pages"] >= 1
            assert isinstance(target.get("max_requests_per_day"), int)
            assert target["max_requests_per_day"] >= 1
        assert by_name["justdial"]["enabled"] is False
        assert by_name["justdial"]["pages"] == 3

    def test_starter_url_templates_cover_all_sites(self):
        cfg = self._config()
        assert set(cfg["url_templates"]) == {"justdial", "indiamart", "tradeindia"}

    def test_starter_icp_allowlists_empty(self):
        cfg = self._config()
        assert cfg["icp_categories"] == []
        assert cfg["icp_cities"] == []

    def test_starter_expands_to_100_combos_per_site(self):
        from src.scraper.targets import expand_start_urls
        cfg = self._config()
        combos = expand_start_urls(cfg["categories"], cfg["cities"], cfg["url_templates"])
        assert len([c for c in combos if c.site == "indiamart"]) == 100
        assert len([c for c in combos if c.site == "tradeindia"]) == 100
