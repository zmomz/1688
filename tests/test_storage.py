"""Tests for storage.py — file persistence functions."""

import csv
import json
from pathlib import Path

from models import Product
from storage import generate_filename, save_csv, save_json, save_products


class TestGenerateFilename:
    def test_returns_path(self, tmp_data_dir):
        result = generate_filename("手机壳", "json")
        assert isinstance(result, Path)

    def test_json_extension(self, tmp_data_dir):
        result = generate_filename("test", "json")
        assert result.suffix == ".json"

    def test_csv_extension(self, tmp_data_dir):
        result = generate_filename("test", "csv")
        assert result.suffix == ".csv"

    def test_safe_keyword_sanitization(self, tmp_data_dir):
        result = generate_filename("hello world/test!", "json")
        name = result.stem
        assert "/" not in name
        assert " " not in name
        assert "!" not in name
        assert "hello" in name

    def test_chinese_chars_preserved_in_filename(self, tmp_data_dir):
        import re
        result = generate_filename("手机壳", "json")
        name = result.stem
        # Chinese chars are Unicode alphanumeric, so they pass the isalnum() check
        assert "手机壳" in name
        # Should also contain the timestamp portion
        assert re.search(r"\d{4}-\d{2}-\d{2}_\d{6}", name)

    def test_timestamp_in_filename(self, tmp_data_dir):
        import re
        result = generate_filename("test", "json")
        name = result.stem
        # Should contain YYYY-MM-DD_HHMMSS pattern
        assert re.search(r"\d{4}-\d{2}-\d{2}_\d{6}", name)

    def test_creates_data_dir(self, tmp_path, monkeypatch):
        import config
        new_dir = tmp_path / "subdir" / "data"
        monkeypatch.setattr(config, "DATA_DIR", new_dir)
        generate_filename("test", "json")
        assert new_dir.exists()

    def test_alphanumeric_keyword_preserved(self, tmp_data_dir):
        result = generate_filename("abc123", "json")
        assert "abc123" in result.stem


class TestSaveJson:
    def test_saves_valid_json(self, tmp_path, sample_product):
        filepath = tmp_path / "out.json"
        save_json([sample_product], filepath)
        data = json.loads(filepath.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "123456"

    def test_chinese_not_escaped(self, tmp_path, sample_product):
        filepath = tmp_path / "out.json"
        save_json([sample_product], filepath)
        content = filepath.read_text(encoding="utf-8")
        assert "测试产品" in content

    def test_empty_list(self, tmp_path):
        filepath = tmp_path / "out.json"
        save_json([], filepath)
        data = json.loads(filepath.read_text(encoding="utf-8"))
        assert data == []

    def test_multiple_products(self, tmp_path):
        products = [Product(id=str(i), title=f"p{i}") for i in range(5)]
        filepath = tmp_path / "out.json"
        save_json(products, filepath)
        data = json.loads(filepath.read_text(encoding="utf-8"))
        assert len(data) == 5

    def test_creates_parent_dirs(self, tmp_path):
        filepath = tmp_path / "sub" / "dir" / "out.json"
        save_json([], filepath)
        assert filepath.exists()

    def test_json_is_indented(self, tmp_path, sample_product):
        filepath = tmp_path / "out.json"
        save_json([sample_product], filepath)
        content = filepath.read_text(encoding="utf-8")
        # Indented JSON has newlines
        assert "\n" in content


class TestSaveCsv:
    def test_saves_csv_file(self, tmp_path, sample_product):
        filepath = tmp_path / "out.csv"
        save_csv([sample_product], filepath)
        assert filepath.exists()

    def test_csv_has_header_row(self, tmp_path, sample_product):
        filepath = tmp_path / "out.csv"
        save_csv([sample_product], filepath)
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            assert set(reader.fieldnames) == set(Product.csv_headers())

    def test_csv_data_row(self, tmp_path, sample_product):
        filepath = tmp_path / "out.csv"
        save_csv([sample_product], filepath)
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["id"] == "123456"
            assert rows[0]["title"] == "测试产品"

    def test_empty_list_no_write(self, tmp_path):
        filepath = tmp_path / "out.csv"
        save_csv([], filepath)
        assert not filepath.exists()

    def test_multiple_products(self, tmp_path):
        products = [Product(id=str(i), title=f"p{i}") for i in range(3)]
        filepath = tmp_path / "out.csv"
        save_csv(products, filepath)
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 3

    def test_creates_parent_dirs(self, tmp_path, sample_product):
        filepath = tmp_path / "sub" / "dir" / "out.csv"
        save_csv([sample_product], filepath)
        assert filepath.exists()


class TestSaveProducts:
    def test_json_format(self, tmp_data_dir, sample_product):
        filepath = save_products([sample_product], "test", "json")
        assert filepath.suffix == ".json"
        assert filepath.exists()
        data = json.loads(filepath.read_text(encoding="utf-8"))
        assert len(data) == 1

    def test_csv_format(self, tmp_data_dir, sample_product):
        filepath = save_products([sample_product], "test", "csv")
        assert filepath.suffix == ".csv"
        assert filepath.exists()

    def test_default_format_is_json(self, tmp_data_dir, sample_product):
        filepath = save_products([sample_product], "test")
        assert filepath.suffix == ".json"

    def test_returns_path(self, tmp_data_dir, sample_product):
        result = save_products([sample_product], "test", "json")
        assert isinstance(result, Path)
