from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from playwright.sync_api import ConsoleMessage, Locator, Page, sync_playwright

BASE_URL = os.environ.get(
    "CONVERTER_PREVIEW_URL",
    "http://127.0.0.1:8000/_design/converter/",
)
OUTPUT_DIR = Path(
    os.environ.get(
        "CONVERTER_PREVIEW_SCREENSHOT_DIR",
        "artifacts/converter-preview",
    )
)

VIEWPORTS = (
    ("desktop-1440", 1440, 1100),
    ("tablet-768", 768, 1024),
    ("mobile-390", 390, 844),
    ("reflow-320", 320, 700),
)


def _box(locator: Locator) -> dict[str, float]:
    box = locator.bounding_box()
    if box is None:
        raise RuntimeError("Expected visible component has no bounding box")
    return box


def _assert_minimum_size(
    locator: Locator,
    *,
    min_width: float = 0,
    min_height: float = 0,
    label: str,
) -> None:
    box = _box(locator)
    if box["width"] + 0.5 < min_width or box["height"] + 0.5 < min_height:
        raise RuntimeError(
            f"{label} is undersized: {box['width']:.1f}x{box['height']:.1f}; "
            f"expected at least {min_width:.1f}x{min_height:.1f}",
        )


def _assert_preview_integrity(page: Page, *, viewport_width: int) -> None:
    heading = page.locator("h1")
    if heading.count() != 1 or heading.inner_text().strip() != "Converter primitives":
        raise RuntimeError("Converter preview must expose exactly one expected H1")

    disclaimer = page.locator("#converter-preview-disclaimer")
    if "not a rate quote" not in disclaimer.inner_text().lower():
        raise RuntimeError("Illustrative-rate disclaimer is missing")

    overflow = page.evaluate(
        """() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
        })""",
    )
    if overflow["scrollWidth"] > overflow["clientWidth"] + 1:
        raise RuntimeError(
            f"Horizontal overflow detected: {overflow['scrollWidth']} > {overflow['clientWidth']}",
        )

    amount_height = 60 if viewport_width <= 480 else 64
    selector_height = 68 if viewport_width <= 480 else 72
    convert_height = 52 if viewport_width <= 480 else 48

    _assert_minimum_size(
        page.locator(".qa-amount-control").first,
        min_height=amount_height,
        label="Amount control",
    )
    _assert_minimum_size(
        page.locator("#workspace-source"),
        min_height=selector_height,
        label="Source trigger",
    )
    workspace = page.locator(".qa-workspace")
    _assert_minimum_size(
        workspace.get_by_role("button", name="Swap source and destination"),
        min_width=48,
        min_height=48,
        label="Workspace swap",
    )
    _assert_minimum_size(
        workspace.get_by_role("button", name="Convert"),
        min_height=convert_height,
        label="Workspace convert",
    )

    error_input = page.locator("#preview-amount-error")
    if error_input.get_attribute("aria-invalid") != "true":
        raise RuntimeError("Amount error sample is missing aria-invalid=true")

    page.keyboard.press("Tab")
    first_focus = page.evaluate("document.activeElement?.className ?? ''")
    if "qa-skip-link" not in first_focus:
        raise RuntimeError(f"Skip link is not first in keyboard order: {first_focus!r}")

    # Shared header contract: brand, five primary routes, then account action.
    # Keep each keyboard stop explicit so navigation regressions remain visible.
    for expected_text in (
        "Cultural Currency",
        "Convert",
        "Plan",
        "Compare",
        "Explore",
        "Saved",
        "Sign in",
    ):
        page.keyboard.press("Tab")
        focused = page.evaluate(
            """() => ({
                tagName: document.activeElement?.tagName ?? "",
                text: document.activeElement?.textContent?.trim() ?? "",
            })"""
        )
        if focused != {"tagName": "A", "text": expected_text}:
            raise RuntimeError(f"Expected header focus {expected_text!r}, got {focused!r}")

    page.keyboard.press("Tab")
    active_id = page.evaluate("document.activeElement?.id ?? ''")
    if active_id != "workspace-amount":
        raise RuntimeError(f"Amount input must follow global navigation: {active_id!r}")

    focus_shadow = page.locator(".qa-amount-control").first.evaluate(
        "element => getComputedStyle(element).boxShadow",
    )
    if focus_shadow == "none":
        raise RuntimeError("Amount focus treatment is not visibly rendered")

    if page.get_by_text("Reference rate", exact=True).count() < 1:
        raise RuntimeError("Reference-rate status text is missing")
    if page.get_by_text("Cached", exact=True).count() < 1:
        raise RuntimeError("Cached status text is missing")
    if page.get_by_text("Historical", exact=True).count() < 1:
        raise RuntimeError("Historical status text is missing")

    source_box = _box(page.locator(".qa-workspace__context--source"))
    destination_box = _box(page.locator(".qa-workspace__context--destination"))
    if viewport_width >= 1024 and abs(source_box["y"] - destination_box["y"]) > 2:
        raise RuntimeError("Wide bilateral contexts must remain simultaneous")
    if viewport_width < 1024 and destination_box["y"] <= source_box["y"]:
        raise RuntimeError(
            "Compact bilateral contexts must preserve source-before-destination order"
        )


def _record_console_error(errors: list[str], message: ConsoleMessage) -> None:
    if message.type == "error":
        errors.append(message.text)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        for name, width, height in VIEWPORTS:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            page = context.new_page()
            console_errors: list[str] = []

            page.on("console", partial(_record_console_error, console_errors))

            response = page.goto(BASE_URL, wait_until="networkidle")
            if response is None or not response.ok:
                status = response.status if response else "no response"
                raise RuntimeError(f"Converter preview request failed for {name}: {status}")

            _assert_preview_integrity(page, viewport_width=width)

            if console_errors:
                raise RuntimeError(
                    f"Browser console errors for {name}: " + " | ".join(console_errors),
                )

            page.screenshot(
                path=str(OUTPUT_DIR / f"{name}.png"),
                full_page=True,
            )
            context.close()

        browser.close()


if __name__ == "__main__":
    main()
