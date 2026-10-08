"""Reject ambiguous and malformed financial JSON before any application work."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.http import JsonResponse
from django.test import RequestFactory
from django.urls import reverse

from apps.exchange.api_v1 import _json_body


@pytest.mark.parametrize(
    "body",
    [
        '{"amount":"1.00","amount":"100.00"}',
        '{"itemPrice":"1.00","itemPrice":"999.00"}',
        '{"amount":"1.00","extra":{"a":1,"a":2}}',
        '{"amount":"1.00","extra":NaN}',
        '{"amount":"1.00","extra":Infinity}',
        '{"amount":"1.00","extra":-Infinity}',
        '{"amount":"1.00","extra":' + "[" * 1100 + "0" + "]" * 1100 + "}",
    ],
)
@pytest.mark.parametrize("endpoint", ["api_v1_conversion", "api_v1_shopping_estimate"])
def test_strict_financial_json_rejects_invalid_ambiguity_before_provider(client, body, endpoint):
    with (
        patch("apps.exchange.api_v1.consume_conversion_quota") as quota,
        patch("apps.exchange.api_v1.run_converter_submission") as conversion,
        patch("apps.exchange.api_v1_shopping.build_latest_quote_gateway") as shopping,
    ):
        response = client.post(
            reverse(endpoint),
            data=body,
            content_type="application/json",
        )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "invalid_json",
        "message": "Request body must contain valid UTF-8 JSON.",
    }
    assert response["Cache-Control"] == "private, no-store"
    quota.assert_not_called()
    conversion.assert_not_called()
    shopping.assert_not_called()


def test_strict_json_preserves_valid_decimal_strings_and_nested_unique_objects():
    request = RequestFactory().post(
        "/api/v1/conversions/",
        data='{"amount":"123.40","extra":{"safe":true,"nested":{"x":"ok"}}}',
        content_type="application/json",
    )
    assert _json_body(request) == {
        "amount": "123.40",
        "extra": {"safe": True, "nested": {"x": "ok"}},
    }


def test_json_nesting_limit_is_explicit_across_python_versions():
    def parse_with_list_depth(depth: int):
        body = '{"amount":"1.00","extra":' + "[" * depth + "0" + "]" * depth + "}"
        request = RequestFactory().post(
            "/api/v1/conversions/", data=body, content_type="application/json"
        )
        return _json_body(request)

    at_limit = parse_with_list_depth(63)
    too_deep = parse_with_list_depth(64)

    assert not isinstance(at_limit, JsonResponse)
    assert at_limit["amount"] == "1.00"
    assert isinstance(too_deep, JsonResponse)
    assert too_deep.status_code == 400
    assert b'"invalid_json"' in too_deep.content


def test_numeric_json_inputs_are_not_promoted_to_financial_decimal_strings():
    request = RequestFactory().post(
        "/api/v1/conversions/",
        data='{"amount":1e99999}',
        content_type="application/json",
    )
    result = _json_body(request)
    assert not isinstance(result, JsonResponse)
    assert not isinstance(result["amount"], str)


def test_size_limit_still_precedes_json_duplicate_validation(client):
    body = '{"amount":"1","amount":"' + "x" * (17 * 1024) + '"}'
    with patch("apps.exchange.api_v1.run_converter_submission") as conversion:
        response = client.post(
            reverse("api_v1_conversion"),
            data=body,
            content_type="application/json",
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    conversion.assert_not_called()
