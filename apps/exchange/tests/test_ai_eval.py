from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.exchange.ai.contracts import ProviderExplanation
from integrations.gemini.models import ProviderUsage


def test_offline_eval_runs_without_provider_or_secret():
    stdout = StringIO()
    with patch(
        "apps.exchange.management.commands.evaluate_runtime_explanation.GeminiStructuredClient"
    ) as client_factory:
        call_command("evaluate_runtime_explanation", stdout=stdout)

    assert "OFFLINE PASS: 4" in stdout.getvalue()
    client_factory.assert_not_called()


def test_live_eval_requires_explicit_server_secret():
    with override_settings(GEMINI_API_KEY=""):
        with pytest.raises(CommandError, match="GEMINI_API_KEY"):
            call_command("evaluate_runtime_explanation", live=True)


def test_eval_rejects_malformed_model_identifier_before_provider_call():
    with pytest.raises(CommandError, match="Invalid Gemini model"):
        call_command(
            "evaluate_runtime_explanation",
            live=True,
            models=["../../not-a-model"],
        )


def test_live_eval_can_explicitly_compare_candidate_model(monkeypatch):
    class FakeDrafter:
        def __init__(self, *, client, model):
            self.model = model

        def draft(self, packet):
            conversion_fact = next(f for f in packet.facts if f.id == "conversion")
            rate_fact = next(f for f in packet.facts if f.id == "rate")
            scope_fact = next(f for f in packet.facts if f.id == "reference_scope")
            return ProviderExplanation(
                payload={
                    "short_answer": {
                        "text": conversion_fact.statement,
                        "supporting_fact_ids": ["conversion"],
                    },
                    "key_factors": [
                        {
                            "text": rate_fact.statement,
                            "supporting_fact_ids": ["rate"],
                        }
                    ],
                    "watch_out_for": {
                        "text": scope_fact.statement,
                        "supporting_fact_ids": ["reference_scope"],
                    },
                    "next_step": {
                        "text": "Use this reference observation as a comparison point.",
                        "supporting_fact_ids": ["reference_scope"],
                    },
                },
                provider_model=self.model,
                response_id=None,
                usage=ProviderUsage(),
            )

    monkeypatch.setattr(
        "apps.exchange.management.commands.evaluate_runtime_explanation.GeminiExplanationDrafter",
        FakeDrafter,
    )
    with (
        override_settings(GEMINI_API_KEY="server-secret"),
        patch(
            "apps.exchange.management.commands.evaluate_runtime_explanation.GeminiStructuredClient",
            return_value=object(),
        ),
    ):
        stdout = StringIO()
        call_command(
            "evaluate_runtime_explanation",
            live=True,
            models=["gemini-3.5-flash-lite"],
            stdout=stdout,
        )

    assert "LIVE PASS [gemini-3.5-flash-lite]: 4 cases" in stdout.getvalue()
