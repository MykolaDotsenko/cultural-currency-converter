from __future__ import annotations

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from apps.common.presentation.media_view_models import ImageViewModel


class ImageFrameTemplateTests(SimpleTestCase):
    def _image(self, **overrides):
        values = {
            "src": "/media/sourced/destination.webp",
            "ratio": "4 / 3",
            "alt": "Evening street scene in Helsinki",
            "decorative": False,
            "kind": "contemporary_photo",
            "label": "Helsinki destination photograph",
            "width": 1600,
            "height": 1200,
        }
        values.update(overrides)
        return ImageViewModel(**values)

    def test_managed_image_defaults_to_lazy_async_loading(self):
        html = render_to_string(
            "components/media/image_frame.html",
            {"image": self._image()},
        )

        self.assertIn('loading="lazy"', html)
        self.assertIn('decoding="async"', html)
        self.assertIn('alt="Evening street scene in Helsinki"', html)
        self.assertIn('width="1600"', html)
        self.assertIn('height="1200"', html)
        self.assertNotIn('aria-hidden="true"', html)
        self.assertNotIn("fetchpriority=", html)
        self.assertNotIn("object-position:", html)

    def test_hero_can_be_eager_and_high_priority(self):
        html = render_to_string(
            "components/media/image_frame.html",
            {
                "image": self._image(ratio="16 / 9", width=1920, height=1080),
                "loading": "eager",
                "fetchpriority": "high",
            },
        )

        self.assertIn('loading="eager"', html)
        self.assertIn('fetchpriority="high"', html)
        self.assertIn('width="1920"', html)
        self.assertIn('height="1080"', html)

    def test_presentation_can_override_display_ratio_without_changing_intrinsic_dimensions(self):
        html = render_to_string(
            "components/media/image_frame.html",
            {
                "image": self._image(ratio="4 / 3", width=1600, height=1200),
                "display_ratio": "16 / 9",
            },
        )

        self.assertIn('style="aspect-ratio: 16 / 9"', html)
        self.assertIn('width="1600"', html)
        self.assertIn('height="1200"', html)

    def test_managed_focal_position_controls_cover_crop(self):
        html = render_to_string(
            "components/media/image_frame.html",
            {
                "image": self._image(
                    focal_position="25% 62.5%",
                    width=1600,
                    height=1200,
                )
            },
        )

        self.assertIn('style="object-position: 25% 62.5%"', html)
        self.assertIn('width="1600"', html)
        self.assertIn('height="1200"', html)

    def test_licence_and_change_disclosure_render_when_available(self):
        html = render_to_string(
            "components/media/image_frame.html",
            {
                "image": self._image(
                    attribution_text="Example Photographer · CC BY-SA 4.0",
                    source_url="https://example.com/photo",
                    licence_id="CC BY-SA 4.0",
                    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
                    change_note="Resized and optimized for web.",
                )
            },
        )

        self.assertIn("CC BY-SA 4.0", html)
        self.assertIn('href="https://creativecommons.org/licenses/by-sa/4.0/"', html)
        self.assertIn("Resized and optimized for web.", html)

    def test_decorative_managed_image_is_hidden_from_accessibility_tree(self):
        html = render_to_string(
            "components/media/image_frame.html",
            {"image": self._image(alt="", decorative=True)},
        )

        self.assertIn('alt=""', html)
        self.assertIn('aria-hidden="true"', html)

    def test_caption_and_attribution_render_semantically(self):
        html = render_to_string(
            "components/media/image_frame.html",
            {
                "image": self._image(
                    caption="Helsinki city centre at dusk.",
                    attribution_text="Example Photographer · CC BY 4.0",
                    source_url="https://example.com/photo",
                ),
            },
        )

        self.assertIn("<figcaption", html)
        self.assertIn("Helsinki city centre at dusk.", html)
        self.assertIn("Example Photographer · CC BY 4.0", html)
        self.assertIn('href="https://example.com/photo"', html)
