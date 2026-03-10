"""Tests for models.py — Product dataclass and SessionExpiredError."""

import json

import pytest

from models import Product, SessionExpiredError


class TestProductDefaults:
    def test_default_values(self, empty_product):
        assert empty_product.id == ""
        assert empty_product.title == ""
        assert empty_product.url == ""
        assert empty_product.price_min is None
        assert empty_product.price_max is None
        assert empty_product.price_unit == "元"
        assert empty_product.moq is None
        assert empty_product.moq_unit == ""
        assert empty_product.supplier_name == ""
        assert empty_product.supplier_url == ""
        assert empty_product.supplier_location == ""
        assert empty_product.supplier_years is None
        assert empty_product.image_url == ""
        assert empty_product.image_urls == []
        assert empty_product.specs == {}
        assert empty_product.sales_count == ""
        assert empty_product.scraped_at  # should be auto-populated

    def test_scraped_at_auto_populated(self):
        p = Product()
        assert p.scraped_at is not None
        assert len(p.scraped_at) > 0
        # Should be ISO format
        assert "T" in p.scraped_at

    def test_mutable_defaults_not_shared(self):
        p1 = Product()
        p2 = Product()
        p1.image_urls.append("a.jpg")
        p1.specs["k"] = "v"
        assert p2.image_urls == []
        assert p2.specs == {}


class TestProductToDict:
    def test_all_fields_present(self, sample_product):
        d = sample_product.to_dict()
        assert d["id"] == "123456"
        assert d["title"] == "测试产品"
        assert d["url"] == "https://detail.1688.com/offer/123456.html"
        assert d["price_min"] == 1.50
        assert d["price_max"] == 3.20
        assert d["price_unit"] == "元"
        assert d["moq"] == 2
        assert d["moq_unit"] == "件"
        assert d["supplier_name"] == "测试供应商"
        assert d["supplier_url"] == "https://shop.1688.com/test"
        assert d["supplier_location"] == "浙江 义乌"
        assert d["supplier_years"] == 5
        assert d["image_url"] == "https://example.com/img.jpg"
        assert d["image_urls"] == [
            "https://example.com/img1.jpg",
            "https://example.com/img2.jpg",
        ]
        assert d["specs"] == {"材质": "塑料", "颜色": "红色"}
        assert d["sales_count"] == "1000+"
        assert d["scraped_at"] == "2025-01-01T00:00:00+00:00"

    def test_dict_has_17_keys(self, sample_product):
        d = sample_product.to_dict()
        assert len(d) == 17

    def test_empty_product_to_dict(self, empty_product):
        d = empty_product.to_dict()
        assert d["id"] == ""
        assert d["price_min"] is None
        assert d["image_urls"] == []
        assert d["specs"] == {}

    def test_to_dict_is_json_serializable(self, sample_product):
        d = sample_product.to_dict()
        serialized = json.dumps(d, ensure_ascii=False)
        assert "测试产品" in serialized


class TestProductCsvHeaders:
    def test_returns_list(self):
        headers = Product.csv_headers()
        assert isinstance(headers, list)

    def test_header_count(self):
        assert len(Product.csv_headers()) == 17

    def test_expected_headers_present(self):
        headers = Product.csv_headers()
        for field in ["id", "title", "url", "price_min", "price_max", "specs"]:
            assert field in headers

    def test_headers_match_to_dict_keys(self, sample_product):
        headers = Product.csv_headers()
        dict_keys = list(sample_product.to_dict().keys())
        assert headers == dict_keys


class TestProductToCsvRow:
    def test_returns_dict_of_strings(self, sample_product):
        row = sample_product.to_csv_row()
        for v in row.values():
            assert isinstance(v, str)

    def test_none_becomes_empty_string(self, empty_product):
        row = empty_product.to_csv_row()
        assert row["price_min"] == ""
        assert row["price_max"] == ""
        assert row["supplier_years"] == ""
        assert row["moq"] == ""

    def test_image_urls_semicolon_joined(self, sample_product):
        row = sample_product.to_csv_row()
        assert row["image_urls"] == "https://example.com/img1.jpg;https://example.com/img2.jpg"

    def test_specs_json_encoded(self, sample_product):
        row = sample_product.to_csv_row()
        specs = json.loads(row["specs"])
        assert specs == {"材质": "塑料", "颜色": "红色"}

    def test_empty_image_urls(self, empty_product):
        row = empty_product.to_csv_row()
        assert row["image_urls"] == ""

    def test_empty_specs(self, empty_product):
        row = empty_product.to_csv_row()
        assert json.loads(row["specs"]) == {}


class TestSessionExpiredError:
    def test_is_exception(self):
        assert issubclass(SessionExpiredError, Exception)

    def test_can_raise_and_catch(self):
        with pytest.raises(SessionExpiredError, match="test message"):
            raise SessionExpiredError("test message")

    def test_empty_message(self):
        err = SessionExpiredError()
        assert str(err) == ""
