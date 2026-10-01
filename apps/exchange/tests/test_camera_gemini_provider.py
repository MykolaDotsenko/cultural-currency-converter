from __future__ import annotations

from apps.exchange.ai.providers.gemini_camera import GeminiCameraAmountExtractor
from apps.exchange.camera import CameraCandidateKind, CameraConfidence, SanitizedCameraImage
from integrations.gemini.models import ProviderUsage, StructuredGeneration


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def generate_json_with_image(self, **kwargs):
        self.calls.append(kwargs)
        return StructuredGeneration(
            data=self.payload,
            provider_model="gemini-camera-snapshot",
            response_id="camera-response",
            usage=ProviderUsage(input_tokens=20, output_tokens=7, total_tokens=27),
        )


def test_gemini_camera_extractor_requests_minimal_money_fields_only():
    client = FakeClient(
        {
            "candidates": [
                {
                    "amount": "4800",
                    "currency_code": "JPY",
                    "kind": "total",
                    "confidence": "high",
                }
            ]
        }
    )
    extractor = GeminiCameraAmountExtractor(
        client=client,
        model="gemini-3.1-flash-lite",
    )
    image = SanitizedCameraImage(
        data=b"sanitized",
        mime_type="image/jpeg",
        width=1200,
        height=800,
    )

    result = extractor.extract(image, expected_currency="JPY")

    assert result.provider_model == "gemini-camera-snapshot"
    assert result.provider_response_id == "camera-response"
    assert result.candidates[0].amount.as_tuple().digits == (4, 8, 0, 0)
    assert result.candidates[0].kind is CameraCandidateKind.TOTAL
    assert result.candidates[0].confidence is CameraConfidence.HIGH

    call = client.calls[0]
    assert call["model"] == "gemini-3.1-flash-lite"
    assert call["image_bytes"] == b"sanitized"
    assert call["image_mime_type"] == "image/jpeg"
    assert "Expected trip currency: JPY" in call["prompt"]

    schema = call["response_json_schema"]
    candidate_properties = schema["properties"]["candidates"]["items"]["properties"]
    assert set(candidate_properties) == {"amount", "currency_code", "kind", "confidence"}
