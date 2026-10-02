from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from playwright.sync_api import ConsoleMessage, Page, sync_playwright

BASE_URL = os.environ.get(
    "SHELL_PREVIEW_URL",
    "http://127.0.0.1:8000/_design/shell/",
)
OUTPUT_DIR = Path(
    os.environ.get(
        "SHELL_PREVIEW_SCREENSHOT_DIR",
        "artifacts/shell-preview",
    )
)

VIEWPORTS = (
    ("desktop-1440", 1440, 1000),
    ("tablet-768", 768, 1024),
    ("mobile-390", 390, 844),
    ("reflow-320", 320, 700),
)


def _assert_shell_integrity(page: Page) -> None:
    heading = page.locator("h1")
    if heading.count() != 1 or heading.inner_text().strip() != "Quiet Atlas foundation":
        raise RuntimeError("Quiet Atlas shell must expose exactly one expected H1")

    if page.locator('[data-country-theme="fi"]').count() != 1:
        raise RuntimeError("Source Finland atmosphere scope is missing")

    if page.locator('[data-country-theme="jp"]').count() != 1:
        raise RuntimeError("Destination Japan atmosphere scope is missing")

    font_state = page.evaluate(
        """() => {
            const family = getComputedStyle(document.body).fontFamily;
            const font_resources = performance
                .getEntriesByType("resource")
                .map((entry) => entry.name)
                .filter((name) => /\.(woff2?|ttf|otf)(\?|$)/i.test(name));

            return {
                family,
                font_resources,
            };
        }"""
    )
    if "system-ui" not in font_state["family"] or font_state["font_resources"]:
        raise RuntimeError(
            "Quiet Atlas typography must use the stable system stack without "
            f"runtime webfont requests: {font_state!r}"
        )

    overflow = page.evaluate(
        """() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
        })"""
    )
    if overflow["scrollWidth"] > overflow["clientWidth"] + 1:
        raise RuntimeError(
            f"Horizontal overflow detected: {overflow['scrollWidth']} > {overflow['clientWidth']}",
        )

    page.keyboard.press("Tab")
    active_class = page.evaluate("document.activeElement?.className ?? ''")
    if "qa-skip-link" not in active_class:
        raise RuntimeError(f"Skip link is not first in keyboard order: {active_class!r}")


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
                raise RuntimeError(f"Shell preview request failed for {name}: {status}")

            _assert_shell_integrity(page)

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
