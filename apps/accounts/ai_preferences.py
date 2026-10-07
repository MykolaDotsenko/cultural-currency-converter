from __future__ import annotations

from dataclasses import dataclass

from django.db import DatabaseError

from apps.accounts.models import (
    AccountPreferences,
    AnswerDetail,
    PreferredLanguage,
    TravelStyle,
)


@dataclass(frozen=True, slots=True)
class ExplanationPreferences:
    locale: str = PreferredLanguage.ENGLISH
    answer_detail: str = AnswerDetail.BALANCED
    travel_style: str = TravelStyle.BALANCED

    @property
    def focus_instruction_suffix(self) -> str:
        instructions: list[str] = []

        if self.answer_detail == AnswerDetail.CONCISE:
            instructions.append(
                "The user explicitly prefers concise explanations. Keep every section short and "
                "use only the minimum supported key factors."
            )
        elif self.answer_detail == AnswerDetail.DETAILED:
            instructions.append(
                "The user explicitly prefers detailed explanations. Use the available structured "
                "space when the supplied facts support it, but never add facts."
            )

        if self.travel_style == TravelStyle.BUDGET:
            instructions.append(
                "For emphasis only, prioritize supplied price, budget and explicit payment-cost "
                "facts when relevant. Do not infer affordability, savings or recommendations."
            )
        elif self.travel_style == TravelStyle.COMFORT:
            instructions.append(
                "For emphasis only, prioritize supplied payment, cash, card and ATM convenience "
                "facts when relevant. Do not infer service quality or recommendations."
            )

        return " ".join(instructions)


def explanation_preferences(user) -> ExplanationPreferences:
    if not getattr(user, "is_authenticated", False):
        return ExplanationPreferences()

    try:
        row = (
            AccountPreferences.objects.filter(user=user)
            .values("preferred_language", "answer_detail", "travel_style")
            .first()
        )
    except DatabaseError:
        return ExplanationPreferences()

    if not row:
        return ExplanationPreferences()

    locale = row["preferred_language"]
    answer_detail = row["answer_detail"]
    travel_style = row["travel_style"]

    if locale not in PreferredLanguage.values:
        locale = PreferredLanguage.ENGLISH
    if answer_detail not in AnswerDetail.values:
        answer_detail = AnswerDetail.BALANCED
    if travel_style not in TravelStyle.values:
        travel_style = TravelStyle.BALANCED

    return ExplanationPreferences(
        locale=locale,
        answer_detail=answer_detail,
        travel_style=travel_style,
    )
