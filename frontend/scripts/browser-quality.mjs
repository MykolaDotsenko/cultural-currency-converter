import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { chromium, firefox, webkit } from "playwright";

import {
  assertBuildPerformanceBudgets,
  measureBuildAssets,
  PERFORMANCE_BUDGET_SOURCE,
  PERFORMANCE_BUDGETS,
} from "./performance-budgets.mjs";

const BASE_URL = process.env.BROWSER_QUALITY_BASE_URL ?? "http://127.0.0.1:8000";
const BROWSER_ENGINE = process.env.BROWSER_QUALITY_ENGINE ?? "chromium";
const BROWSER_SCOPE = process.env.BROWSER_QUALITY_SCOPE ?? "full";
const BROWSER_TYPES = { chromium, firefox, webkit };
const browserType = BROWSER_TYPES[BROWSER_ENGINE];
assertBrowserConfiguration();
const OUTPUT_DIR = resolve(process.cwd(), "../artifacts/browser-quality");
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const LOCAL_STATE_KEY = "cultural-currency:local-preferences:v1";

const SURFACES = [
  { name: "shell", path: "/_design/shell/" },
  { name: "converter", path: "/_design/converter/" },
  { name: "current-converter", path: "/" },
  { name: "destination-mode", path: "/destination/" },
  { name: "destination-comparison", path: "/compare/" },
  { name: "explore", path: "/explore/" },
  { name: "same-amount", path: "/explore/same-amount/" },
  { name: "city-money-profile", path: "/city/JP/tokyo/" },
  {
    name: "money-culture-story",
    path: "/story/?source_country=FI&source_currency=EUR&destination_country=JP&destination_currency=JPY&selected_date=2026-09-21&historical=0",
  },
  { name: "saved-state", path: "/saved/" },
  { name: "account-login", path: "/accounts/login/" },
  { name: "account-signup", path: "/accounts/signup/" },
  { name: "rate-series", path: "/_design/rate-series/" },
];

function assertBrowserConfiguration() {
  if (!browserType) {
    throw new Error(`Unsupported browser engine: ${BROWSER_ENGINE}`);
  }
  if (!["full", "smoke"].includes(BROWSER_SCOPE)) {
    throw new Error(`Unsupported browser quality scope: ${BROWSER_SCOPE}`);
  }
}

async function assertContentSecurityPolicyHeader(response, label) {
  const headers = await response.headers();
  const policy = headers["content-security-policy"] ?? "";

  assert(policy.includes("default-src 'self'"), `${label}: CSP default-src is missing`);
  assert(policy.includes("script-src 'self'"), `${label}: CSP script-src is missing`);
  assert(
    policy.includes("script-src-attr 'none'"),
    `${label}: inline script attributes are not blocked`,
  );
  assert(!policy.includes("'unsafe-eval'"), `${label}: CSP unexpectedly allows unsafe-eval`);
  assert(policy.includes("object-src 'none'"), `${label}: object-src is not locked down`);
  assert(policy.includes("frame-ancestors 'none'"), `${label}: frame-ancestors is not locked down`);
  assert(
    policy.includes("report-uri /security/csp-report/"),
    `${label}: CSP reporting endpoint is missing`,
  );
}

const VIEWPORTS = [
  { name: "wide-1440", width: 1440, height: 1000 },
  { name: "transition-1023", width: 1023, height: 900 },
  { name: "transition-1025", width: 1025, height: 900 },
  { name: "mobile-430", width: 430, height: 932 },
  { name: "mobile-390", width: 390, height: 844 },
  { name: "mobile-360", width: 360, height: 800 },
  { name: "reflow-640", width: 640, height: 900 },
  { name: "reflow-320", width: 320, height: 700 },
];

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function consumeExpectedConsoleErrors(
  consoleErrors,
  startIndex,
  { label, expected, requireEvidence = false },
) {
  const newErrors = consoleErrors.slice(startIndex);
  if (requireEvidence) {
    assert(newErrors.length > 0, `${label}: expected browser error evidence was not emitted`);
  }
  const unexpected = newErrors.filter(
    (message) => !expected.some((fragment) => message.includes(fragment)),
  );
  assert(unexpected.length === 0, `${label}: unexpected console errors: ${unexpected.join(" | ")}`);
  consoleErrors.splice(startIndex, newErrors.length);
}

async function waitForStableLayout(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
  });
}

async function assertNoHorizontalOverflow(page, label) {
  const dimensions = await page.evaluate(() => {
    const clientWidth = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll("body *")]
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          id: element.id,
          className: typeof element.className === "string" ? element.className.trim() : "",
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
          ignoreInternalOverflow: element.matches("input, textarea, .qa-visually-hidden"),
        };
      })
      .filter((element) => {
        const outsideViewport = element.right > clientWidth + 1 || element.left < -1;
        const internalOverflowIsRelevant =
          !element.ignoreInternalOverflow && element.scrollWidth > element.clientWidth + 1;
        return outsideViewport || internalOverflowIsRelevant;
      })
      .sort(
        (a, b) =>
          Math.max(b.right - clientWidth, b.scrollWidth - b.clientWidth) -
          Math.max(a.right - clientWidth, a.scrollWidth - a.clientWidth),
      )
      .slice(0, 5);

    return {
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth,
      offenders,
    };
  });
  assert(
    dimensions.scrollWidth <= dimensions.clientWidth + 1,
    `${label}: horizontal overflow ${dimensions.scrollWidth} > ${dimensions.clientWidth}; offenders: ${JSON.stringify(dimensions.offenders)}`,
  );
}

async function assertAxe(page, label) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  if (results.violations.length > 0) {
    const details = results.violations
      .map((violation) => {
        const targets = violation.nodes
          .slice(0, 3)
          .flatMap((node) => node.target)
          .join(", ");
        return `${violation.id} [${violation.impact ?? "unknown"}]: ${targets}`;
      })
      .join("\n");
    throw new Error(`${label}: axe found ${results.violations.length} violation(s)\n${details}`);
  }
}

async function assertKeyboardFocus(page, surfaceName) {
  const focusBaseline = await page.evaluate(() => {
    const autofocus = document.querySelector("[autofocus]");
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    return {
      autofocusTag: autofocus?.tagName ?? "",
      autofocusId: autofocus?.id ?? "",
    };
  });
  assert(
    focusBaseline.autofocusTag === "",
    `${surfaceName}: unexpected autofocus target: ${JSON.stringify(focusBaseline)}`,
  );

  await page.keyboard.press("Tab");
  const first = await page.evaluate(() => ({
    className: document.activeElement?.className ?? "",
    tagName: document.activeElement?.tagName ?? "",
  }));
  assert(
    String(first.className).includes("qa-skip-link"),
    `${surfaceName}: skip link is not the first keyboard target: ${JSON.stringify(first)}`,
  );

  if (surfaceName === "converter") {
    await page.keyboard.press("Tab");
    const second = await page.evaluate(() => ({
      tagName: document.activeElement?.tagName ?? "",
      text: document.activeElement?.textContent?.trim() ?? "",
    }));
    assert(
      second.tagName === "A" && second.text === "Sign in",
      `converter: expected Sign in as second focus target, got ${JSON.stringify(second)}`,
    );
    await page.keyboard.press("Tab");
    const activeId = await page.evaluate(() => document.activeElement?.id ?? "");
    assert(
      activeId === "workspace-amount",
      `converter: unexpected amount focus target ${activeId}`,
    );
  }

  if (surfaceName === "current-converter") {
    for (const expectedText of [
      "Plan by destination",
      "Compare destinations",
      "Explore",
      "Saved & recent",
      "Sign in",
    ]) {
      await page.keyboard.press("Tab");
      const focused = await page.evaluate(() => ({
        tagName: document.activeElement?.tagName ?? "",
        text: document.activeElement?.textContent?.trim() ?? "",
      }));
      assert(
        focused.tagName === "A" && focused.text === expectedText,
        `current-converter: expected ${expectedText} header focus, got ${JSON.stringify(focused)}`,
      );
    }

    await page.keyboard.press("Tab");
    const amountId = await page.evaluate(() => document.activeElement?.id ?? "");
    assert(amountId === "id_amount", `current-converter: expected amount focus, got ${amountId}`);

    for (const expectedId of [
      "source-picker-trigger",
      "swap-contexts",
      "destination-picker-trigger",
      "id_rate_mode_0",
    ]) {
      await page.keyboard.press("Tab");
      const nextId = await page.evaluate(() => document.activeElement?.id ?? "");
      assert(
        nextId === expectedId,
        `current-converter: expected focus on ${expectedId}, got ${nextId}`,
      );
    }
  }
}

async function assertAiExplanationReliability(page, consoleErrors) {
  const region = page.locator("#conversion-explanation-region");
  const announcer = page.locator("#explanation-announcer");
  const clientStatus = page.locator("#explanation-client-status");
  const ratePrompt = page.getByRole("button", { name: "What does this rate mean?" });
  const paymentPrompt = page.getByRole("button", { name: "Why might my bank or card differ?" });
  const loading = page.locator("#explanation-loading");
  const resultAmountBefore = await page
    .locator("#current-conversion-result .qa-result__output")
    .innerText();

  await ratePrompt.waitFor();
  await paymentPrompt.waitFor();
  assert(
    (await ratePrompt.getAttribute("aria-controls")) === "conversion-explanation-region" &&
      (await ratePrompt.getAttribute("hx-disabled-elt")) === "this",
    "current-converter/ai: quick prompt is missing scoped request controls",
  );
  assert(
    (await region.getAttribute("aria-busy")) === "false" &&
      (await region.getAttribute("data-ai-pending-requests")) === "0",
    "current-converter/ai: explanation region is missing idle busy-state semantics",
  );
  assert(
    (await announcer.getAttribute("role")) === "status" &&
      (await announcer.getAttribute("aria-live")) === "polite" &&
      (await announcer.getAttribute("aria-atomic")) === "true",
    "current-converter/ai: persistent screen-reader announcer is missing",
  );
  assert(
    (await loading.getAttribute("aria-hidden")) === "true",
    "current-converter/ai: visual loading indicator must not duplicate the live announcement",
  );

  const waitForExplanation = (promptId) =>
    page.waitForResponse((response) => {
      if (
        response.request().method() !== "POST" ||
        new URL(response.url()).pathname !== "/conversion/explain/"
      ) {
        return false;
      }
      const body = response.request().postData() ?? "";
      return new URLSearchParams(body).get("prompt_id") === promptId;
    });

  const viewport = page.viewportSize();
  const exerciseCancellation = BROWSER_SCOPE === "full" && viewport?.width === 1440;
  let cancellationConsoleStart = null;

  if (exerciseCancellation) {
    cancellationConsoleStart = consoleErrors.length;
    await ratePrompt.click();
    await page.waitForFunction(
      () =>
        document.getElementById("conversion-explanation-region")?.getAttribute("aria-busy") ===
        "true",
    );
    await page.waitForFunction(() =>
      document
        .getElementById("explanation-announcer")
        ?.textContent?.includes("Generating explanation: What does this rate mean?"),
    );
    assert(await ratePrompt.isDisabled(), "current-converter/ai: active prompt was not disabled");
    assert(
      !(await paymentPrompt.isDisabled()),
      "current-converter/ai: replacement prompt was incorrectly disabled",
    );
    assert(
      await loading.isVisible(),
      "current-converter/ai: loading indicator did not become visible",
    );

    const paymentResponsePromise = waitForExplanation("payment_difference");
    await paymentPrompt.click();
    const paymentResponse = await paymentResponsePromise;
    assert(
      paymentResponse.status() === 200,
      `current-converter/ai: timeout fallback returned ${paymentResponse.status()}`,
    );
  } else {
    await paymentPrompt.focus();
    assert(
      (await page.evaluate(() => document.activeElement?.getAttribute("value"))) ===
        "payment_difference",
      "current-converter/ai: payment quick prompt could not receive keyboard focus",
    );
    const paymentResponsePromise = waitForExplanation("payment_difference");
    await page.keyboard.press("Enter");
    const paymentResponse = await paymentResponsePromise;
    assert(
      paymentResponse.status() === 200,
      `current-converter/ai: timeout fallback returned ${paymentResponse.status()}`,
    );
  }

  await region.getByText("Built-in explanation", { exact: true }).waitFor();
  const fallbackText = await region.innerText();
  assert(
    fallbackText.includes("Why might my bank or card show a different result?") &&
      fallbackText.includes("Choose the same question again to retry"),
    `current-converter/ai: timeout fallback/retry copy mismatch: ${JSON.stringify(fallbackText)}`,
  );
  assert(
    (await region.getAttribute("aria-busy")) === "false" &&
      (await region.getAttribute("data-ai-pending-requests")) === "0",
    "current-converter/ai: explanation region stayed busy after fallback",
  );
  await page.waitForFunction(() =>
    document
      .getElementById("explanation-announcer")
      ?.textContent?.includes("Built-in explanation ready. Live AI is unavailable."),
  );
  assert(
    await page.evaluate(() =>
      document.activeElement?.matches("#conversion-explanation-region [data-ai-explanation-focus]"),
    ),
    "current-converter/ai: fallback result did not receive focus",
  );
  assert(
    (await page.locator("#current-conversion-result .qa-result__output").innerText()) ===
      resultAmountBefore,
    "current-converter/ai: fallback changed the deterministic conversion result",
  );

  if (exerciseCancellation) {
    await page.waitForTimeout(300);
    assert(
      (await region.innerText()).includes("Why might my bank or card show a different result?"),
      "current-converter/ai: superseded request overwrote the replacement fallback",
    );
    consumeExpectedConsoleErrors(consoleErrors, cancellationConsoleStart ?? consoleErrors.length, {
      label: "current-converter/ai cancellation",
      expected: ["htmx:afterRequest", "htmx:sendAbort"],
    });
  }

  await ratePrompt.focus();
  assert(
    (await page.evaluate(() => document.activeElement?.getAttribute("value"))) === "rate_meaning",
    "current-converter/ai: rate quick prompt could not receive keyboard focus",
  );
  const rateResponsePromise = waitForExplanation("rate_meaning");
  await page.keyboard.press("Enter");
  const rateResponse = await rateResponsePromise;
  assert(
    rateResponse.status() === 200,
    `current-converter/ai: generated explanation returned ${rateResponse.status()}`,
  );
  await region.getByText("AI explanation", { exact: true }).waitFor();
  const generatedText = (await region.textContent()) ?? "";
  assert(
    generatedText.includes("What does this reference rate mean?") &&
      generatedText.includes("What matters most") &&
      generatedText.includes("Watch out for") &&
      generatedText.includes("Next step"),
    `current-converter/ai: structured generated answer mismatch: ${JSON.stringify(generatedText)}`,
  );
  await page.waitForFunction(() =>
    document
      .getElementById("explanation-announcer")
      ?.textContent?.includes("AI explanation ready."),
  );
  assert(
    await page.evaluate(() =>
      document.activeElement?.matches("#conversion-explanation-region [data-ai-explanation-focus]"),
    ),
    "current-converter/ai: generated result did not receive focus",
  );
  assert(
    (await region.getAttribute("aria-busy")) === "false" &&
      (await region.getAttribute("data-ai-pending-requests")) === "0",
    "current-converter/ai: generated explanation left the region busy",
  );
  assert(
    (await page.locator("#current-conversion-result .qa-result__output").innerText()) ===
      resultAmountBefore,
    "current-converter/ai: generated explanation changed the deterministic conversion result",
  );

  if (exerciseCancellation) {
    const consoleErrorStart = consoleErrors.length;
    await page.route("**/conversion/explain/", (route) => route.abort("failed"), { times: 1 });
    await ratePrompt.click();
    await page
      .getByText(
        "The explanation request could not be completed. Choose the question again to retry.",
        { exact: true },
      )
      .waitFor();
    assert(
      (await region.getAttribute("aria-busy")) === "false",
      "current-converter/ai: transport failure left the region busy",
    );
    await page.waitForFunction(() =>
      document
        .getElementById("explanation-announcer")
        ?.textContent?.includes("Explanation request failed."),
    );
    assert(
      (await clientStatus.getAttribute("tabindex")) === "-1" &&
        (await page.evaluate(() => document.activeElement?.id)) === "explanation-client-status",
      "current-converter/ai: transport failure status did not receive focus",
    );

    const recoveryResponsePromise = waitForExplanation("rate_meaning");
    await ratePrompt.click();
    const recoveryResponse = await recoveryResponsePromise;
    assert(
      recoveryResponse.status() === 200,
      `current-converter/ai: retry after transport failure returned ${recoveryResponse.status()}`,
    );
    await region.getByText("AI explanation", { exact: true }).waitFor();
    assert(
      (await clientStatus.textContent())?.trim() === "",
      "current-converter/ai: retry did not clear the transport failure message",
    );
    await page.waitForTimeout(50);
    consumeExpectedConsoleErrors(consoleErrors, consoleErrorStart, {
      label: "current-converter/ai intentional transport failure",
      expected: [
        "htmx:afterRequest",
        "htmx:sendAbort",
        "htmx:sendError",
        "Failed to load resource: net::ERR_FAILED",
      ],
      requireEvidence: true,
    });
  }

  await assertAxe(page, "current-converter/ai-explanation");
}
async function assertCurrentConverterFlow(page, consoleErrors) {
  const waitForPost = () =>
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" && new URL(response.url()).pathname === "/",
    );

  await page.locator("#id_amount").fill("-1");
  const invalidSubmit = waitForPost();
  await page.locator(".qa-primary-button").click();
  const invalidSubmitResponse = await invalidSubmit;
  assert(
    invalidSubmitResponse.status() === 422,
    `current-converter: invalid submit returned ${invalidSubmitResponse.status()} instead of 422`,
  );
  await page.getByText("Enter zero or a positive amount.").waitFor();

  await page.locator("#id_source_currency").evaluate((element) => {
    if (!(element instanceof HTMLSelectElement)) {
      throw new Error("Expected source currency control to be a select");
    }
    element.value = "";
  });
  await page.locator("#id_destination_currency").evaluate((element) => {
    if (!(element instanceof HTMLSelectElement)) {
      throw new Error("Expected destination currency control to be a select");
    }
    element.value = "";
  });
  const multipleInvalidSubmit = waitForPost();
  await page.locator(".qa-primary-button").click();
  const multipleInvalidSubmitResponse = await multipleInvalidSubmit;
  assert(
    multipleInvalidSubmitResponse.status() === 422,
    `current-converter: multiple-error submit returned ${multipleInvalidSubmitResponse.status()} instead of 422`,
  );
  await page.locator("#conversion-error-summary").waitFor();
  const validationFocusId = await page.evaluate(() => document.activeElement?.id ?? "");
  assert(
    validationFocusId === "conversion-error-summary",
    `current-converter: expected focus on validation summary, got ${validationFocusId}`,
  );

  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });

  // Real Payment Estimate is a separate progressive surface: it must use the
  // trusted conversion snapshot, render validation errors, and never mark the
  // successful conversion itself as failed.
  await page.locator("#id_amount").fill("100");
  await Promise.all([waitForPost(), page.locator(".qa-primary-button").click()]);
  await page.getByRole("heading", { name: "Estimate what explicit fees may change" }).waitFor();

  const bilateralRoute = page.locator("[data-bilateral-route]");
  await bilateralRoute.waitFor();
  assert(
    (await bilateralRoute.locator(".qa-bilateral-result__side").count()) === 2,
    "current-converter: bilateral result must expose exactly two contextual sides",
  );
  const routeCurrencies = (
    await bilateralRoute.locator(".qa-bilateral-result__currency").allTextContents()
  ).map((value) => value.trim());
  assert(
    JSON.stringify(routeCurrencies) ===
      JSON.stringify([
        await page.locator("#id_source_currency").inputValue(),
        await page.locator("#id_destination_currency").inputValue(),
      ]),
    `current-converter: bilateral route currencies drifted from the canonical controls: ${JSON.stringify(routeCurrencies)}`,
  );
  assert(
    (await bilateralRoute.locator("img").count()) === 0,
    "current-converter: bilateral identity must not introduce flag or decorative image chrome",
  );
  assert(
    (await bilateralRoute
      .locator(".qa-bilateral-result__connector[aria-hidden='true']")
      .count()) === 1,
    "current-converter: bilateral connector must remain decorative for assistive technology",
  );
  await assertAiExplanationReliability(page, consoleErrors);

  const waitForPaymentEstimate = () =>
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/payment/estimate/",
    );

  const paymentEstimateForm = page.locator(".qa-payment-estimate__form");
  const paymentEstimateToken = await paymentEstimateForm
    .locator('input[name="payment_estimate_token"]')
    .inputValue();
  assert(
    paymentEstimateToken.length > 40 && paymentEstimateToken.split(":").length >= 3,
    `current-converter: payment estimate token is missing or malformed in DOM; length=${paymentEstimateToken.length}`,
  );
  const postedPaymentToken = await paymentEstimateForm.evaluate((form) => {
    if (!(form instanceof HTMLFormElement)) return "";
    return String(new FormData(form).get("payment_estimate_token") ?? "");
  });
  assert(
    postedPaymentToken === paymentEstimateToken,
    "current-converter: payment estimate token is not included in form data",
  );

  // Exercise both parser branches explicitly. A three-digit fractional form
  // such as 1.001 is intentionally treated as ambiguous before precision
  // validation, while 1.0001 is unambiguously a too-precise EUR amount.
  await page.locator("#id_fx_markup_percent").fill("2");
  await page.locator("#id_source_fixed_fee").fill("1.001");
  await page.locator("#id_destination_fixed_fee").fill("0");
  const ambiguousEstimate = waitForPaymentEstimate();
  await page.getByRole("button", { name: "Calculate estimate" }).click();
  const ambiguousEstimateResponse = await ambiguousEstimate;
  assert(
    ambiguousEstimateResponse.status() === 422,
    `current-converter: ambiguous payment estimate returned ${ambiguousEstimateResponse.status()} instead of 422`,
  );
  const ambiguousEstimateBody = await ambiguousEstimateResponse.text();
  assert(
    ambiguousEstimateBody.includes(
      "This amount is ambiguous. Enter it without thousands separators.",
    ),
    `current-converter: ambiguous payment-estimate response omitted parser error; body=${ambiguousEstimateBody.slice(0, 800)}`,
  );
  const ambiguousFeeError = page.locator("#source_fixed_fee-error");
  await ambiguousFeeError.waitFor();
  assert(
    (await ambiguousFeeError.textContent())?.includes(
      "This amount is ambiguous. Enter it without thousands separators.",
    ),
    "current-converter: ambiguous payment-estimate error did not render into the target region",
  );
  assert(
    await page.locator("[data-previous-result-note]").isHidden(),
    "current-converter: payment-estimate validation incorrectly marked the conversion as failed",
  );

  await page.locator("#id_source_fixed_fee").fill("1.0001");
  const precisionEstimate = waitForPaymentEstimate();
  await page.getByRole("button", { name: "Calculate estimate" }).click();
  const precisionEstimateResponse = await precisionEstimate;
  assert(
    precisionEstimateResponse.status() === 422,
    `current-converter: over-precise payment estimate returned ${precisionEstimateResponse.status()} instead of 422`,
  );
  await page.getByText("This currency supports at most 2 decimal places.").waitFor();
  assert(
    await page.locator("[data-previous-result-note]").isHidden(),
    "current-converter: payment-estimate precision error incorrectly marked the conversion as failed",
  );

  await page.locator("#id_fx_markup_percent").fill("2");
  await page.locator("#id_source_fixed_fee").fill("1");
  await page.locator("#id_destination_fixed_fee").fill("220");
  const validEstimate = waitForPaymentEstimate();
  await page.getByRole("button", { name: "Calculate estimate" }).click();
  const validEstimateResponse = await validEstimate;
  assert(
    validEstimateResponse.status() === 200,
    `current-converter: payment estimate returned ${validEstimateResponse.status()} instead of 200`,
  );
  await page.getByText("Estimated destination value", { exact: true }).waitFor();
  await page
    .getByText("This is a scenario estimate, not a bank/card/ATM quote.", {
      exact: false,
    })
    .waitFor();
  await assertAxe(page, "current-converter/payment-estimate");

  // Budget interpretation is a separate deterministic progressive surface. It
  // must carry a signed Money Context scope, keep its assumptions explicit,
  // and leave the successful conversion untouched.
  const budgetForm = page.locator(".qa-budget-interpretation__form");
  await budgetForm.waitFor();
  const budgetContextToken = await budgetForm
    .locator('input[name="budget_context_token"]')
    .inputValue();
  assert(
    budgetContextToken.length > 40 && budgetContextToken.split(":").length >= 3,
    `current-converter: budget context token is missing or malformed; length=${budgetContextToken.length}`,
  );

  const waitForBudgetInterpretation = () =>
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/budget/interpret/",
    );

  await budgetForm.locator("#id_duration_days").fill("5");
  await budgetForm.locator("#id_travelers").fill("1");
  const budgetFormValidity = await budgetForm.evaluate((form) => {
    if (!(form instanceof HTMLFormElement)) {
      throw new Error("Expected budget interpretation surface to be a form");
    }
    const invalidControls = Array.from(form.elements)
      .filter((control) => control instanceof HTMLElement && "checkValidity" in control)
      .filter((control) => !control.checkValidity())
      .map((control) => ({
        id: control.id,
        name: control.getAttribute("name"),
        value: "value" in control ? String(control.value) : "",
        validationMessage: "validationMessage" in control ? String(control.validationMessage) : "",
      }));
    return { valid: form.checkValidity(), invalidControls };
  });
  assert(
    budgetFormValidity.valid,
    `current-converter: budget form is blocked by native validation before submit: ${JSON.stringify(budgetFormValidity.invalidControls)}`,
  );
  const budgetResponsePromise = waitForBudgetInterpretation();
  await budgetForm.getByRole("button", { name: "Interpret budget" }).click();
  const budgetResponse = await budgetResponsePromise;
  assert(
    budgetResponse.status() === 200,
    `current-converter: budget interpretation returned ${budgetResponse.status()} instead of 200`,
  );
  await page.getByText("Reference-basket comparison", { exact: true }).waitFor();
  await page.getByText("not a full trip-cost forecast", { exact: false }).waitFor();
  await page.getByRole("link", { name: "Sign in to save" }).waitFor();
  assert(
    (await page.locator('form[action="/saved/scenarios/budget/create/"]').count()) === 0,
    "current-converter: anonymous budget interpretation exposed an account-save form",
  );
  assert(
    await page.locator("[data-previous-result-note]").isHidden(),
    "current-converter: budget interpretation incorrectly marked the conversion as failed",
  );
  await assertAxe(page, "current-converter/budget-interpretation");

  const budgetAiRegion = page.locator("#budget-explanation-region");
  const budgetAiPrompt = page.getByRole("button", { name: "Explain this budget", exact: true });
  await budgetAiPrompt.waitFor();
  const budgetResultBeforeAi = await page.locator(".qa-budget-interpretation__result").innerText();
  const budgetAiResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/budget/explain/",
  );
  await budgetAiPrompt.click();
  const budgetAiResponse = await budgetAiResponsePromise;
  assert(
    budgetAiResponse.status() === 200,
    `current-converter/budget-ai: explanation returned ${budgetAiResponse.status()}`,
  );
  await budgetAiRegion.locator('[data-ai-generated="true"]').waitFor();
  assert(
    (await budgetAiRegion.getAttribute("aria-busy")) === "false" &&
      (await budgetAiRegion.getAttribute("data-ai-pending-requests")) === "0",
    "current-converter/budget-ai: explanation region did not return to idle state",
  );
  assert(
    await page.evaluate(() =>
      document.activeElement?.matches("#budget-explanation-region [data-ai-explanation-focus]"),
    ),
    "current-converter/budget-ai: swapped explanation did not receive focus",
  );
  assert(
    (await page.locator(".qa-budget-interpretation__result").innerText()) === budgetResultBeforeAi,
    "current-converter/budget-ai: explanation changed the deterministic budget result",
  );
  assert(
    !/cheapest|winner|best value|more affordable|less affordable/i.test(
      (await budgetAiRegion.innerText()) ?? "",
    ),
    "current-converter/budget-ai: explanation introduced ranking or affordability language",
  );
  await assertAxe(page, "current-converter/budget-ai");

  await page.evaluate((key) => localStorage.removeItem(key), LOCAL_STATE_KEY);
  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });

  await page.locator("#source-picker-trigger").click();
  const sourceDialog = page.locator('[data-picker-dialog="source"]');
  const viewport = page.viewportSize();
  if (viewport && viewport.width <= 480) {
    const dialogBox = await sourceDialog.boundingBox();
    assert(
      dialogBox &&
        dialogBox.x <= 1 &&
        dialogBox.y <= 1 &&
        Math.abs(dialogBox.width - viewport.width) <= 2 &&
        Math.abs(dialogBox.height - viewport.height) <= 2,
      "current-converter/mobile: picker must use the full viewport",
    );
  }

  const search = page.locator("#source-picker-search");
  await page.locator("#source-picker-listbox").waitFor();
  await page.waitForFunction(() => {
    const first = document.querySelector("#source-picker-listbox [data-picker-option]");
    return (
      first?.getAttribute("data-country-code") === "FI" &&
      first?.getAttribute("data-currency-code") === "EUR" &&
      first.textContent?.includes("Current selection")
    );
  });
  await search.fill("JPY");
  await page.locator("#source-picker-listbox").waitFor();
  await page.waitForFunction(() => {
    const list = document.querySelector("#source-picker-listbox");
    if (!(list instanceof HTMLElement) || list.dataset.commitWired !== "true") return false;
    const options = Array.from(list.querySelectorAll("[data-picker-option]"));
    return (
      options.length === 2 &&
      options[0]?.getAttribute("data-country-code") === "" &&
      options[0]?.getAttribute("data-currency-code") === "JPY" &&
      options[1]?.getAttribute("data-country-code") === "JP" &&
      options[1]?.getAttribute("data-currency-code") === "JPY"
    );
  });
  await search.press("ArrowDown");
  await search.press("ArrowDown");
  await search.press("Enter");
  await page.locator('[data-picker-dialog="source"]').waitFor({ state: "hidden" });
  assert(
    (await page.locator("#id_source_country").inputValue()) === "JP" &&
      (await page.locator("#id_source_currency").inputValue()) === "JPY",
    "current-converter: Japan/JPY picker selection did not commit",
  );

  await page.locator("#id_amount").fill("12");
  await Promise.all([waitForPost(), page.locator(".qa-primary-button").click()]);
  await page.locator("#current-conversion-result").waitFor();

  const resultText = await page.locator("#current-conversion-result").innerText();
  assert(resultText.includes("12 JPY"), "current-converter: same-currency input is missing");
  assert(
    resultText.includes("Exact same-currency rate"),
    "current-converter: same-currency provenance is missing",
  );
  const identitySummary = page.locator("#current-conversion-result .qa-result-summary");
  await identitySummary.waitFor();
  const identitySummaryText = await identitySummary.innerText();
  const identitySummaryKind = await identitySummary.getAttribute("data-summary-kind");
  const identitySummaryKicker = await identitySummary
    .locator(".qa-foundation-kicker")
    .textContent();
  assert(
    identitySummaryKind === "identity" &&
      identitySummaryKicker?.trim() === "At a glance" &&
      identitySummaryText.includes("No exchange-rate lookup is needed") &&
      identitySummaryText.includes("exact 1:1"),
    `current-converter: deterministic smart summary mismatch: kind=${identitySummaryKind}, kicker=${JSON.stringify(identitySummaryKicker)}, text=${JSON.stringify(identitySummaryText)}`,
  );
  assert(
    new URL(page.url()).searchParams.get("convert") === "1",
    "current-converter: successful HTMX conversion did not push a bookmarkable URL",
  );
  await page.waitForFunction(() =>
    document.getElementById("conversion-announcer")?.textContent?.includes("12 JPY"),
  );
  assert(
    (await page.locator("#conversion-announcer").count()) === 1,
    "current-converter: expected exactly one persistent conversion announcer",
  );
  assert(
    (await page.locator('#conversion-announcer[role="status"][aria-live="polite"]').count()) === 1,
    "current-converter: expected one persistent conversion result live region",
  );
  assert(
    (await page.locator('#conversion-result-region .qa-visually-hidden[role="status"]').count()) ===
      0,
    "current-converter: swapped result markup contains a duplicate hidden result announcer",
  );

  await page.getByRole("link", { name: "Everyday value" }).waitFor();
  await page.getByRole("link", { name: "Payment context" }).waitFor();

  const exploreLabels = (await page.locator(".qa-explore-nav a").allTextContents()).map((label) =>
    label.trim(),
  );
  assert(
    JSON.stringify(exploreLabels) ===
      JSON.stringify(["Everyday value", "Payment context", "Money & culture"]),
    `current-converter: Explore must expose exactly the three contextual paths, got ${JSON.stringify(exploreLabels)}`,
  );

  const postResultHierarchy = await page.evaluate(() => {
    const result = document.querySelector("#current-conversion-result");
    const destinationContext = document.querySelector(".qa-destination-context");
    const story = document.querySelector(".qa-story-entry");
    const historical = document.querySelector(".qa-historical-trend-entry");
    const save = document.querySelector(".qa-local-save-control");
    const precedes = (first, second) =>
      Boolean(
        first &&
          second &&
          (first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
      );

    return {
      complete: Boolean(result && destinationContext && save),
      resultBeforeContext: precedes(result, destinationContext),
      contextBeforeSave: precedes(destinationContext, save),
      storyBeforeSave: story ? precedes(story, save) : true,
      historicalBeforeSave: historical ? precedes(historical, save) : true,
    };
  });
  assert(
    postResultHierarchy.complete &&
      postResultHierarchy.resultBeforeContext &&
      postResultHierarchy.contextBeforeSave &&
      postResultHierarchy.storyBeforeSave &&
      postResultHierarchy.historicalBeforeSave,
    `current-converter: post-result hierarchy drifted: ${JSON.stringify(postResultHierarchy)}`,
  );

  assert(
    (await page.locator("#money-culture-story-slot[aria-live]").count()) === 0 &&
      (await page.locator("#historical-trend-slot[aria-live]").count()) === 0,
    "current-converter: large progressive fragments must not be live regions",
  );
  await page.getByText("Cup of coffee", { exact: true }).waitFor();
  await page.getByText("Tokyo Metro regular ticket", { exact: true }).waitFor();
  await page.getByRole("heading", { name: "Paying in Japan" }).waitFor();

  const destinationMedia = page.locator(".qa-destination-context [data-media-role]");
  if ((await destinationMedia.count()) > 0) {
    for (const mediaRole of await destinationMedia.all()) {
      const image = mediaRole.locator(".qa-media__image");
      await image.waitFor();
      assert(
        Number(await image.getAttribute("width")) > 0 &&
          Number(await image.getAttribute("height")) > 0,
        "current-converter/media: managed photography lost intrinsic dimensions",
      );
      const frame = mediaRole.locator(".qa-media__frame");
      assert(
        (await frame.count()) === 1,
        "current-converter/media: reviewed photography lost its reserved aspect-ratio frame",
      );
      const caption = mediaRole.locator(".qa-media__caption");
      if ((await caption.count()) === 1) {
        assert(
          (await caption.locator("a[href^='https://']").count()) > 0,
          "current-converter/media: visible media provenance lost its HTTPS source/licence link",
        );
      }
    }
  }

  await page.waitForFunction((key) => {
    const raw = localStorage.getItem(key);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    return parsed.version === 1 && parsed.recent?.length === 1;
  }, LOCAL_STATE_KEY);
  await page.getByRole("button", { name: "Save pair" }).click();
  await page.getByRole("button", { name: "Remove saved pair" }).waitFor();
  const savedState = await page.evaluate(
    (key) => JSON.parse(localStorage.getItem(key) ?? "{}"),
    LOCAL_STATE_KEY,
  );
  assert(
    savedState.favourites?.length === 1,
    "current-converter: favourite was not stored locally",
  );
  assert(
    savedState.recent?.length === 1,
    "current-converter: successful conversion was not recorded once",
  );
  assert(savedState.recent[0]?.amount === "12", "current-converter: recent amount is incorrect");
  assert(
    savedState.recent[0]?.sourceCountry === "JP",
    "current-converter: recent source context is incorrect",
  );
  await assertAxe(page, "current-converter/result");

  const waitForStory = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" && new URL(response.url()).pathname === "/story/",
  );
  await page.getByRole("link", { name: "Explore money & culture" }).click();
  await waitForStory;
  await page.locator(".qa-story-surface").waitFor();
  const storyText = await page.locator(".qa-story-surface").innerText();
  assert(
    storyText.includes("The sourced story behind this currency context"),
    "current-converter: progressive money-and-culture story did not render",
  );
  assert(
    storyText.includes("Temporal scope:"),
    "current-converter: story temporal provenance is missing",
  );
  assert(
    (await page.locator(".qa-story-surface a[href^='https://']").count()) > 0,
    "current-converter: story source links are missing",
  );
  await assertAxe(page, "current-converter/story");

  await page.locator("#id_rate_mode_1").check();
  await page.locator("#id_requested_date").waitFor({ state: "visible" });
  const historicalPost = waitForPost();
  await page.locator("#id_requested_date").fill("1998-06-15");
  await historicalPost;
  const historicalResult = page.locator("#current-conversion-result");
  await historicalResult.waitFor();
  await historicalResult.getByText("15 Jun 1998", { exact: true }).first().waitFor();

  const historicalText = await historicalResult.innerText();
  assert(
    historicalText.includes("Historical exact 1:1"),
    "current-converter: historical identity status is missing",
  );
  assert(
    historicalText.includes("Requested date") && historicalText.includes("15 Jun 1998"),
    "current-converter: requested historical date is missing",
  );
  assert(
    historicalText.includes("Observation date"),
    "current-converter: historical observation date is missing",
  );
  const historicalSummary = historicalResult.locator(".qa-result-summary");
  await historicalSummary.waitFor();
  assert(
    (await historicalSummary.innerText()).includes("does not describe historical purchasing power"),
    "current-converter: historical smart summary lost its purchasing-power boundary",
  );
  const historicalUrl = new URL(page.url());
  assert(
    historicalUrl.searchParams.get("rate_mode") === "historical" &&
      historicalUrl.searchParams.get("requested_date") === "1998-06-15",
    "current-converter: historical conversion did not push a stable deep link",
  );

  assert(
    (await page.locator(".qa-destination-context").count()) === 0,
    "current-converter: historical result exposed current destination context before opt-in",
  );
  await page.getByRole("link", { name: "See today’s travel context" }).waitFor();

  const waitForCurrentContext = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === "/destination/current-context/",
  );
  await page.getByRole("link", { name: "See today’s travel context" }).click();
  await waitForCurrentContext;
  await page
    .getByText("Current destination context — not historical purchasing power.", {
      exact: false,
    })
    .waitFor();
  await page.getByText("Cup of coffee", { exact: true }).waitFor();
  assert(
    (await page.locator("#current-destination-context-slot .qa-explore-nav").count()) === 0,
    "current-converter: opt-in current context duplicated the primary Explore navigation",
  );

  await assertAxe(page, "current-converter/historical-current-context");

  const latestPost = waitForPost();
  await page.locator("#id_rate_mode_0").check();
  await latestPost;
  await page.locator("#current-conversion-result").waitFor();
  await page.locator("[data-historical-date-field]").waitFor({ state: "hidden" });

  const previousAmount = await page
    .locator("#current-conversion-result .qa-result__input")
    .innerText();
  await page.evaluate(() => {
    const announcer = document.getElementById("conversion-announcer");
    if (!announcer) throw new Error("Missing conversion announcer");
    window.__qaAnnouncerMutationCount = 0;
    window.__qaAnnouncerObserver = new MutationObserver(() => {
      window.__qaAnnouncerMutationCount += 1;
    });
    window.__qaAnnouncerObserver.observe(announcer, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  });
  const invalidRefresh = waitForPost();
  await page.locator("#id_amount").fill("-1");
  const invalidRefreshResponse = await invalidRefresh;
  assert(
    invalidRefreshResponse.status() === 422,
    `current-converter: invalid progressive refresh returned ${invalidRefreshResponse.status()} instead of 422`,
  );
  await page.getByText("Enter zero or a positive amount.").waitFor();

  const preservedAmount = await page
    .locator("#current-conversion-result .qa-result__input")
    .innerText();
  assert(
    preservedAmount === previousAmount,
    "current-converter: failed refresh replaced the previous successful result",
  );
  await page.getByText("Previous result — fix the changed inputs to update it.").waitFor();
  const failedRefreshAnnouncements = await page.evaluate(() => {
    window.__qaAnnouncerObserver?.disconnect();
    return window.__qaAnnouncerMutationCount ?? 0;
  });
  assert(
    failedRefreshAnnouncements === 0,
    `current-converter: failed refresh mutated the success announcer ${failedRefreshAnnouncements} time(s)`,
  );

  const correctedRefresh = waitForPost();
  await page.locator("#id_amount").fill("12");
  await correctedRefresh;
  await page.locator("#current-conversion-result").waitFor();
  await page.waitForFunction(
    () => document.querySelector("[data-previous-result-note]")?.hidden === true,
  );

  await Promise.all([waitForPost(), page.locator("#swap-contexts").click()]);
  await page.waitForFunction(() => document.querySelector(".htmx-request") === null);
  const focused = await page.evaluate(() => document.activeElement?.id ?? "");
  assert(focused === "swap-contexts", `current-converter: swap focus moved to ${focused}`);

  const loadingState = await page.locator("#conversion-loading").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      requestActive: element.classList.contains("htmx-request"),
      opacity: style.opacity,
      visibility: style.visibility,
      display: style.display,
    };
  });
  assert(
    !loadingState.requestActive &&
      (loadingState.opacity === "0" ||
        loadingState.visibility === "hidden" ||
        loadingState.display === "none"),
    `current-converter: loading indicator remained visually active after swap: ${JSON.stringify(loadingState)}`,
  );

  for (const message of consoleErrors.filter(
    (entry) =>
      entry.includes("422") &&
      (entry.includes("Unprocessable Content") || entry.includes("Unprocessable Entity")),
  )) {
    consoleErrors.splice(consoleErrors.indexOf(message), 1);
  }
}

async function assertSavedStateFlow(page) {
  const neutralStatus = page.locator("[data-local-storage-status]");
  await page.waitForFunction(() => {
    const status = document.querySelector("[data-local-storage-status]");
    return status?.getAttribute("data-storage-tone") === "neutral";
  });
  assert(
    await page.getByRole("button", { name: "Clear saved pairs" }).isHidden(),
    "saved-state/empty: clear-saved action should not compete with the empty state",
  );
  assert(
    await page.getByRole("button", { name: "Clear recent history" }).isHidden(),
    "saved-state/empty: clear-recents action should not compete with the empty state",
  );
  assert(
    (await neutralStatus.getAttribute("data-storage-tone")) === "neutral",
    "saved-state/empty: ordinary local-storage metadata should remain visually neutral",
  );
  for (const label of ["Explore destinations", "Convert a pair", "Start a conversion"]) {
    assert(
      (await page.getByRole("link", { name: label, exact: true }).count()) === 1,
      `saved-state/empty: missing bounded next action ${label}`,
    );
  }

  const sampleState = {
    version: 1,
    places: [
      {
        id: "JP:tokyo",
        token: "JP:tokyo",
        countryCode: "JP",
        countryName: "Japan",
        citySlug: "tokyo",
        cityName: "Tokyo",
        currencyCode: "JPY",
        savedAt: "2026-09-21T12:00:00.000Z",
      },
    ],
    favourites: [
      {
        id: "FI:EUR:>:JP:JPY",
        sourceCurrency: "EUR",
        destinationCurrency: "JPY",
        sourceCountry: "FI",
        destinationCountry: "JP",
        sourceCountryName: "Finland",
        destinationCountryName: "Japan",
        savedAt: "2026-09-21T12:00:00.000Z",
      },
    ],
    recent: [
      {
        id: "FI:EUR:>:JP:JPY|latest|latest|100",
        sourceCurrency: "EUR",
        destinationCurrency: "JPY",
        sourceCountry: "FI",
        destinationCountry: "JP",
        sourceCountryName: "Finland",
        destinationCountryName: "Japan",
        amount: "100",
        outputAmount: "17450",
        rateMode: "latest",
        requestedDate: "",
        effectiveDate: "2026-09-18",
        convertedAt: "2026-09-21T12:00:00.000Z",
      },
      {
        id: "FI:FIM:>:US:USD|historical|1998-06-15|100",
        sourceCurrency: "FIM",
        destinationCurrency: "USD",
        sourceCountry: "FI",
        destinationCountry: "US",
        sourceCountryName: "Finland",
        destinationCountryName: "United States",
        amount: "100",
        outputAmount: "21.35",
        rateMode: "historical",
        requestedDate: "1998-06-15",
        effectiveDate: "1998-06-15",
        convertedAt: "2026-09-20T12:00:00.000Z",
      },
    ],
  };

  await page.evaluate(({ key, state }) => localStorage.setItem(key, JSON.stringify(state)), {
    key: LOCAL_STATE_KEY,
    state: sampleState,
  });
  await page.reload({ waitUntil: "networkidle" });

  await page.getByRole("heading", { name: "Tokyo, Japan" }).waitFor();
  await page.getByRole("heading", { name: "EUR → JPY" }).waitFor();
  await page.getByText("100 EUR → 17450 JPY", { exact: true }).waitFor();
  await page.getByText("100 FIM → 21.35 USD", { exact: true }).waitFor();

  const savedPlaceRow = page.locator('[data-saved-place-id="JP:tokyo"]');
  const placeConvertHref = await savedPlaceRow
    .getByRole("link", { name: "Convert for Tokyo, Japan", exact: true })
    .getAttribute("href");
  assert(placeConvertHref, "saved-state: saved Tokyo is missing its converter handoff");
  const placeConvert = new URL(placeConvertHref, BASE_URL);
  assert(
    placeConvert.searchParams.get("destination_country") === "JP" &&
      placeConvert.searchParams.get("destination_currency") === "JPY" &&
      placeConvert.searchParams.get("destination_city_slug") === "tokyo",
    `saved-state: saved Tokyo lost canonical destination scope: ${placeConvertHref}`,
  );
  assert(
    (await savedPlaceRow
      .getByRole("link", { name: "Open city profile: Tokyo, Japan", exact: true })
      .getAttribute("href")) === "/city/JP/tokyo/",
    "saved-state: saved Tokyo city-profile handoff drifted",
  );
  const placeCompareHref = await savedPlaceRow
    .getByRole("link", { name: "Compare destination: Tokyo, Japan", exact: true })
    .getAttribute("href");
  assert(placeCompareHref, "saved-state: saved Tokyo is missing Compare");
  const placeCompare = new URL(placeCompareHref, BASE_URL);
  assert(
    placeCompare.pathname === "/compare/" &&
      placeCompare.searchParams.get("left_destination") === "JP:tokyo" &&
      !placeCompare.searchParams.has("right_destination"),
    `saved-state: saved Tokyo Compare handoff drifted: ${placeCompareHref}`,
  );
  assert(
    await savedPlaceRow
      .getByRole("link", { name: "Convert for Tokyo, Japan", exact: true })
      .evaluate((element) => element.classList.contains("qa-primary-button")),
    "saved-state: saved place primary action hierarchy regressed",
  );

  const savedRow = page.locator("[data-saved-pair-id]").first();
  const usePairHref = await savedRow
    .getByRole("link", { name: "Use pair: EUR to JPY", exact: true })
    .getAttribute("href");
  assert(usePairHref, "saved-state: favourite is missing its Use pair URL");
  const usePair = new URL(usePairHref, BASE_URL);
  assert(
    usePair.searchParams.get("load") === "1",
    "saved-state: favourite does not use pair-load mode",
  );
  assert(
    usePair.searchParams.get("amount") === null,
    "saved-state: favourite unexpectedly stores amount",
  );
  assert(
    usePair.searchParams.get("source_country") === "FI",
    "saved-state: favourite source country missing",
  );
  const pairCompareHref = await savedRow
    .getByRole("link", { name: "Compare destination: Japan", exact: true })
    .getAttribute("href");
  assert(pairCompareHref, "saved-state: favourite is missing Compare");
  const pairCompare = new URL(pairCompareHref, BASE_URL);
  assert(
    pairCompare.pathname === "/compare/" &&
      pairCompare.searchParams.get("left_destination") === "JP" &&
      !pairCompare.searchParams.has("right_destination"),
    `saved-state: favourite Compare handoff drifted: ${pairCompareHref}`,
  );
  assert(
    await savedRow
      .getByRole("link", { name: "Use pair: EUR to JPY", exact: true })
      .evaluate((element) => element.classList.contains("qa-primary-button")),
    "saved-state: favourite primary action hierarchy regressed",
  );
  assert(
    await savedRow
      .getByRole("link", { name: "Reverse pair: EUR to JPY", exact: true })
      .evaluate((element) => element.classList.contains("qa-saved-row__text-action")),
    "saved-state: favourite tertiary action hierarchy regressed",
  );

  const latestRecent = page.locator("[data-recent-conversion-id]").first();
  const repeatHref = await latestRecent
    .getByRole("link", { name: "Repeat conversion: 100 EUR to JPY", exact: true })
    .getAttribute("href");
  assert(repeatHref, "saved-state: recent conversion is missing Repeat URL");
  const repeat = new URL(repeatHref, BASE_URL);
  assert(
    repeat.searchParams.get("convert") === "1",
    "saved-state: repeat does not request conversion",
  );
  assert(repeat.searchParams.get("amount") === "100", "saved-state: repeat amount missing");

  const recentCompareHref = await latestRecent
    .getByRole("link", { name: "Compare destination: Japan", exact: true })
    .getAttribute("href");
  assert(recentCompareHref, "saved-state: recent conversion is missing Compare");
  const recentCompare = new URL(recentCompareHref, BASE_URL);
  assert(
    recentCompare.pathname === "/compare/" &&
      recentCompare.searchParams.get("left_destination") === "JP" &&
      !recentCompare.searchParams.has("right_destination"),
    `saved-state: recent Compare handoff drifted: ${recentCompareHref}`,
  );
  assert(
    await latestRecent
      .getByRole("link", { name: "Repeat conversion: 100 EUR to JPY", exact: true })
      .evaluate((element) => element.classList.contains("qa-primary-button")),
    "saved-state: recent primary action hierarchy regressed",
  );

  const swapHref = await latestRecent
    .getByRole("link", { name: "Swap conversion: 100 EUR to JPY", exact: true })
    .getAttribute("href");
  assert(swapHref, "saved-state: recent conversion is missing Swap URL");
  const swap = new URL(swapHref, BASE_URL);
  assert(
    swap.searchParams.get("source_currency") === "JPY" &&
      swap.searchParams.get("destination_currency") === "EUR",
    "saved-state: swap URL did not reverse the pair",
  );
  assert(
    await latestRecent
      .getByRole("link", { name: "Swap conversion: 100 EUR to JPY", exact: true })
      .evaluate((element) => element.classList.contains("qa-saved-row__text-action")),
    "saved-state: recent tertiary action hierarchy regressed",
  );

  assert(
    (await savedRow
      .getByRole("button", { name: "Remove saved pair: EUR to JPY", exact: true })
      .count()) === 1,
    "saved-state: favourite remove action is missing row-specific accessible context",
  );
  await latestRecent
    .getByRole("button", { name: "Remove recent conversion: 100 EUR to JPY", exact: true })
    .click();
  await page.waitForFunction(
    (key) => JSON.parse(localStorage.getItem(key) ?? "{}").recent?.length === 1,
    LOCAL_STATE_KEY,
  );
  assert(
    await page
      .getByRole("button", { name: "Clear saved places" })
      .evaluate((element) => element.classList.contains("qa-destructive-button")),
    "saved-state: Clear saved places is missing destructive-action styling",
  );
  await savedPlaceRow
    .getByRole("button", { name: "Remove saved place: Tokyo, Japan", exact: true })
    .click();
  await page.getByText("Place removed from this browser.", { exact: true }).waitFor();
  await page
    .getByText("No saved places yet. Save a reviewed country or city from Explore.", {
      exact: true,
    })
    .waitFor();
  assert(
    await page.getByRole("button", { name: "Clear saved places" }).isHidden(),
    "saved-state: clear-places action remained visible after the list became empty",
  );

  for (const label of ["Clear saved pairs", "Clear recent history"]) {
    assert(
      await page
        .getByRole("button", { name: label })
        .evaluate((element) => element.classList.contains("qa-destructive-button")),
      `saved-state: ${label} is missing destructive-action styling`,
    );
  }

  await page.getByRole("button", { name: "Clear recent history" }).click();
  await page.getByText("Recent history cleared from this browser.", { exact: true }).waitFor();
  await page.getByText("No recent conversions in this browser yet.", { exact: true }).waitFor();
  assert(
    await page.getByRole("button", { name: "Clear recent history" }).isHidden(),
    "saved-state: clear-recents action remained visible after the list became empty",
  );

  await page.getByRole("button", { name: "Clear saved pairs" }).click();
  await page.getByText("Saved pairs cleared from this browser.", { exact: true }).waitFor();
  await page.getByText("No saved pairs yet.", { exact: false }).waitFor();
  assert(
    await page.getByRole("button", { name: "Clear saved pairs" }).isHidden(),
    "saved-state: clear-saved action remained visible after the list became empty",
  );

  await page.evaluate((key) => localStorage.setItem(key, "{broken"), LOCAL_STATE_KEY);
  await page.reload({ waitUntil: "networkidle" });
  await page
    .getByText("Some local saved data was unreadable or outdated and has been ignored.", {
      exact: false,
    })
    .waitFor();
  assert(
    (await page.locator("[data-local-storage-status]").getAttribute("data-storage-tone")) ===
      "warning",
    "saved-state: corrupt local data did not elevate recovery status",
  );

  await page.evaluate(({ key, state }) => localStorage.setItem(key, JSON.stringify(state)), {
    key: LOCAL_STATE_KEY,
    state: sampleState,
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "EUR → JPY" }).waitFor();
  await assertAxe(page, "saved-state/populated");
}

async function assertAuthenticatedRecentHistoryFlow(page) {
  const localOnlyRecent = {
    version: 1,
    favourites: [],
    places: [
      {
        id: "JP:tokyo",
        token: "JP:tokyo",
        countryCode: "JP",
        countryName: "Japan",
        citySlug: "tokyo",
        cityName: "Tokyo",
        currencyCode: "JPY",
        savedAt: "2026-09-21T12:00:00.000Z",
      },
    ],
    recent: [
      {
        id: "FI:EUR:>:JP:JPY|latest|latest|100",
        sourceCurrency: "EUR",
        destinationCurrency: "JPY",
        sourceCountry: "FI",
        destinationCountry: "JP",
        sourceCountryName: "Finland",
        destinationCountryName: "Japan",
        amount: "100",
        outputAmount: "17450",
        rateMode: "latest",
        requestedDate: "",
        effectiveDate: "2026-09-18",
        convertedAt: "2026-09-21T12:00:00.000Z",
      },
    ],
  };
  await page.evaluate(({ key, state }) => localStorage.setItem(key, JSON.stringify(state)), {
    key: LOCAL_STATE_KEY,
    state: localOnlyRecent,
  });

  const username = `qa-history-${crypto.randomUUID().slice(0, 12)}`;
  const testCredential = `QA-${crypto.randomUUID()}`;
  await page.locator("#id_username").fill(username);
  await page.locator("#id_password1").fill(testCredential);
  await page.locator("#id_password2").fill(testCredential);
  await Promise.all([
    page.waitForURL((url) => url.pathname === "/saved/"),
    page.getByRole("button", { name: "Create account" }).click(),
  ]);

  await page.getByRole("heading", { name: "Account recent history" }).waitFor();
  await page
    .getByText("No account recent history. Browser-only history below stays on this device.", {
      exact: true,
    })
    .waitFor();
  await page.getByText("100 EUR → 17450 JPY", { exact: true }).waitFor();
  assert(
    (await page.locator("[data-account-recent-id]").count()) === 0,
    "account-history: sign-up silently imported browser-local recent history",
  );
  assert(
    (await page.locator("[data-account-place-id]").count()) === 0,
    "account-places: sign-up silently imported browser-local My Places",
  );
  await page.getByRole("heading", { name: "Tokyo, Japan" }).waitFor();
  const importPlaces = page.getByRole("button", {
    name: "Import browser places to account",
    exact: true,
  });
  await importPlaces.waitFor();
  await importPlaces.click();
  await page.waitForLoadState("networkidle");
  assert(
    (await page.locator("[data-account-place-id]").count()) === 1,
    "account-places: explicit import did not create exactly one owner-scoped place",
  );
  const importedLocalPlaceCount = await page.evaluate((key) => {
    const state = JSON.parse(localStorage.getItem(key) ?? "{}");
    return Array.isArray(state.places) ? state.places.length : -1;
  }, LOCAL_STATE_KEY);
  assert(
    importedLocalPlaceCount === 0,
    `account-places: confirmed local copies were not removed after import; count=${importedLocalPlaceCount}`,
  );
  assert(
    (await page.locator('[data-saved-place-id="JP:tokyo"]').count()) === 0,
    "account-places: browser-local row remained after successful explicit import",
  );
  await assertAxe(page, "account-history/post-signup");

  await page.getByRole("link", { name: "Account" }).click();
  await page.getByText("Off by default.", { exact: false }).waitFor();
  await Promise.all([
    page.waitForURL((url) => url.pathname === "/accounts/profile/"),
    page.getByRole("button", { name: "Turn on account history" }).click(),
  ]);
  await page.getByText("Cross-device recent history is on.", { exact: false }).waitFor();

  const conversionUrl = new URL("/", BASE_URL);
  conversionUrl.searchParams.set("convert", "1");
  conversionUrl.searchParams.set("amount", "10.00");
  conversionUrl.searchParams.set("source_country", "FI");
  conversionUrl.searchParams.set("source_currency", "EUR");
  conversionUrl.searchParams.set("destination_country", "FI");
  conversionUrl.searchParams.set("destination_currency", "EUR");
  conversionUrl.searchParams.set("rate_mode", "latest");
  await page.goto(conversionUrl.toString(), { waitUntil: "networkidle" });
  await page.locator('[data-account-recent-recorded="true"]').waitFor();

  const localRecentCount = await page.evaluate((key) => {
    const state = JSON.parse(localStorage.getItem(key) ?? "{}");
    return Array.isArray(state.recent) ? state.recent.length : 0;
  }, LOCAL_STATE_KEY);
  assert(
    localRecentCount === 1,
    `account-history: account-backed conversion duplicated local history; count=${localRecentCount}`,
  );

  await page
    .locator("#conversion-result-region")
    .getByRole("link", { name: "Saved & recent" })
    .click();
  await page.locator("[data-account-recent-id]").first().waitFor();
  assert(
    (await page.locator("[data-account-recent-id]").count()) === 1,
    "account-history: opted-in conversion did not create exactly one account recent row",
  );
  const accountRecentRow = page.locator("[data-account-recent-id]").first();
  assert(
    (await accountRecentRow.getByRole("link", { name: /^Repeat conversion:/ }).count()) === 1,
    "account-history: repeat action is missing row-specific accessible context",
  );
  const accountCompareHref = await accountRecentRow
    .getByRole("link", { name: /^Compare destination:/ })
    .getAttribute("href");
  assert(accountCompareHref, "account-history: compare action is missing");
  const accountCompare = new URL(accountCompareHref, BASE_URL);
  assert(
    accountCompare.pathname === "/compare/" &&
      accountCompare.searchParams.get("left_destination") === "FI" &&
      !accountCompare.searchParams.has("right_destination"),
    `account-history: compare handoff drifted: ${accountCompareHref}`,
  );
  assert(
    (await accountRecentRow.getByRole("button", { name: /^Remove recent conversion:/ }).count()) ===
      1,
    "account-history: remove action is missing row-specific accessible context",
  );
  await page.getByText("100 EUR → 17450 JPY", { exact: true }).waitFor();
  assert(
    await page
      .getByRole("button", { name: "Clear account history" })
      .evaluate((element) => element.classList.contains("qa-destructive-button")),
    "account-history: clear action is missing destructive-action styling",
  );
  await assertAxe(page, "account-history/populated");

  await Promise.all([
    page.waitForURL((url) => url.pathname === "/saved/"),
    page.getByRole("button", { name: "Clear account history" }).click(),
  ]);
  assert(
    (await page.locator("[data-account-recent-id]").count()) === 0,
    "account-history: clear action left account recent rows behind",
  );
  await page.getByText("100 EUR → 17450 JPY", { exact: true }).waitFor();
  await page
    .getByText("No account recent history. Browser-only history below stays on this device.", {
      exact: true,
    })
    .waitFor();

  // Exercise the account-owned trip-continuity loop end to end. The saved
  // scenario must use the same converter/budget contracts and confirmed spend
  // must remain an explicit destination-currency action.
  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
  await page.locator("#id_amount").fill("600");

  const conversionResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/",
  );
  await page.locator(".qa-primary-button").click();
  const conversionResponse = await conversionResponsePromise;
  assert(
    conversionResponse.status() === 200,
    `trip-budget/e2e: conversion returned ${conversionResponse.status()}`,
  );

  const budgetForm = page.locator(".qa-budget-interpretation__form");
  await budgetForm.waitFor();
  await budgetForm.locator("#id_duration_days").fill("5");
  await budgetForm.locator("#id_travelers").fill("1");

  const budgetResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/budget/interpret/",
  );
  await budgetForm.getByRole("button", { name: "Interpret budget" }).click();
  const budgetResponse = await budgetResponsePromise;
  assert(
    budgetResponse.status() === 200,
    `trip-budget/e2e: budget interpretation returned ${budgetResponse.status()}`,
  );

  const saveForm = page.locator(".qa-budget-interpretation__save-form");
  await saveForm.waitFor();
  await saveForm.locator('input[name="title"]').fill("QA Tokyo budget");
  await saveForm.locator('input[name="travel_start_date"]').fill("2099-04-12");
  await saveForm.locator('input[name="travel_end_date"]').fill("2099-04-18");
  const saveScenarioResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/saved/scenarios/budget/create/",
  );
  await saveForm.getByRole("button", { name: "Save budget" }).click();
  const saveScenarioResponse = await saveScenarioResponsePromise;
  assert(
    saveScenarioResponse.status() === 302,
    `trip-budget/e2e: save scenario returned ${saveScenarioResponse.status()} instead of 302`,
  );
  const saveLocation = saveScenarioResponse.headers().location ?? "";
  if (!/^\/saved\/scenarios\/\d+\/$/.test(saveLocation)) {
    if (saveLocation) {
      await page.waitForURL((url) => url.pathname === new URL(saveLocation, BASE_URL).pathname);
    } else {
      await page.waitForLoadState("domcontentloaded");
    }
    const flashMessages = await page.locator('.qa-flash-message, [role="alert"]').allTextContents();
    assert(
      false,
      `trip-budget/e2e: save scenario redirected to ${saveLocation || "(missing location)"}; messages=${flashMessages.join(" | ")}`,
    );
  }
  await page.waitForURL((url) => /^\/saved\/scenarios\/\d+\/$/.test(url.pathname));

  await page.getByRole("heading", { name: "QA Tokyo budget", level: 1 }).waitFor();
  await page.getByRole("heading", { name: "Trip budget remaining" }).waitFor();
  const baselineSummary = await page
    .locator('[aria-labelledby="scenario-trip-budget-title"]')
    .innerText();
  assert(
    baselineSummary.includes("Confirmed spend 0 JPY"),
    `trip-budget/e2e: new saved budget did not start at zero confirmed spend: ${baselineSummary}`,
  );

  // Exercise the real Camera confirmation boundary with the test-only
  // deterministic extractor. The image still goes through decode/re-encode,
  // candidate signing, explicit user confirmation and a separate spend POST.
  await page.getByRole("link", { name: "Scan a price", exact: true }).click();
  await page.getByRole("heading", { name: "Scan a visible price", level: 1 }).waitFor();
  await page.locator('input[type="file"]').setInputFiles({
    name: "qa-price.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z7N8AAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/saved\/scenarios\/\d+\/camera\/$/.test(new URL(response.url()).pathname),
    ),
    page.getByRole("button", { name: "Extract visible amounts", exact: true }).click(),
  ]);
  await page.getByRole("heading", { name: "Choose and confirm a candidate", level: 2 }).waitFor();
  await page.getByRole("heading", { name: "4800 JPY", level: 3 }).waitFor();
  assert(
    (await page.getByText("Image processing is ephemeral", { exact: true }).count()) === 1,
    "camera/e2e: ephemeral-processing privacy boundary is missing",
  );
  await assertAxe(page, "camera/e2e/candidate");

  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/saved\/scenarios\/\d+\/camera\/$/.test(new URL(response.url()).pathname),
    ),
    page.getByRole("button", { name: "Confirm this amount", exact: true }).click(),
  ]);
  await page.getByRole("heading", { name: "4800 JPY", level: 1 }).waitFor();
  await page
    .getByRole("heading", { name: "Ready for an explicit spend handoff", level: 2 })
    .waitFor();
  assert(
    (await page.getByText("The uploaded image itself was not persisted.", { exact: false }).count()) >=
      1,
    "camera/e2e: confirmation page lost the no-raw-media persistence boundary",
  );
  await assertAxe(page, "camera/e2e/confirmed");

  await Promise.all([
    page.waitForURL((url) => /^\/saved\/scenarios\/\d+\/$/.test(url.pathname)),
    page.getByRole("button", { name: "Add to trip budget", exact: true }).click(),
  ]);
  await page.getByText("4800 JPY added to confirmed spend.", { exact: true }).waitFor();

  const updatedSummary = await page
    .locator('[aria-labelledby="scenario-trip-budget-title"]')
    .innerText();
  assert(
    updatedSummary.includes("Confirmed spend 4800 JPY"),
    `trip-budget/e2e: Camera-confirmed spend did not update the saved budget: ${updatedSummary}`,
  );
  assert(
    !updatedSummary.includes("Confirmed spend 0 JPY"),
    "trip-budget/e2e: stale zero-spend state remained after Camera confirmation",
  );
  const remainingMatch = updatedSummary.match(/([0-9]+(?:\.[0-9]+)?) JPY remaining/);
  assert(
    remainingMatch,
    `trip-budget/e2e: updated saved budget omitted remaining amount: ${updatedSummary}`,
  );
  const expectedRemainingText = `${remainingMatch[1]} JPY remaining`;

  // Browser-level Offline Pack evidence: download the actual attachment,
  // inspect its self-contained HTML, then render that HTML without network.
  const [offlineDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download offline pack", exact: true }).click(),
  ]);
  assert(
    /^cultural-currency-.*-offline-\d{4}-\d{2}-\d{2}\.html$/.test(
      offlineDownload.suggestedFilename(),
    ),
    `offline-pack/e2e: unexpected filename ${offlineDownload.suggestedFilename()}`,
  );
  const offlinePath = await offlineDownload.path();
  assert(offlinePath, "offline-pack/e2e: browser did not materialize the downloaded pack");
  const offlineHtml = await readFile(offlinePath, "utf8");
  assert(
    offlineHtml.includes("Offline means stored, not live."),
    "offline-pack/e2e: stored-not-live freshness semantics are missing",
  );
  assert(
    /confirmed spend\s+4800 JPY/i.test(offlineHtml),
    "offline-pack/e2e: Camera-confirmed spend is missing from the downloaded pack",
  );
  assert(
    offlineHtml.includes('data-offline-pack-version="1"') &&
      !offlineHtml.toLowerCase().includes("<script") &&
      !offlineHtml.toLowerCase().includes('rel="stylesheet"'),
    "offline-pack/e2e: downloaded pack is not a self-contained script-free artifact",
  );
  const offlinePage = await page.context().newPage();
  await offlinePage.setContent(offlineHtml, { waitUntil: "load" });
  await offlinePage.getByText("Offline means stored, not live.", { exact: true }).waitFor();
  await assertNoHorizontalOverflow(offlinePage, "offline-pack/e2e");
  await assertAxe(offlinePage, "offline-pack/e2e");
  await offlinePage.close();

  await page.getByRole("button", { name: "Remove entry" }).waitFor();
  await assertNoHorizontalOverflow(page, "trip-budget/e2e");
  await assertAxe(page, "trip-budget/e2e");

  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
  const returningTrip = page.locator(".qa-returning-trip-home");
  await returningTrip.waitFor();
  await returningTrip.getByRole("heading", { name: "QA Tokyo budget", level: 2 }).waitFor();
  const returningTripText = await returningTrip.innerText();
  assert(
    returningTripText.toLowerCase().includes("upcoming trip"),
    `returning-trip/e2e: saved future trip was not promoted on clean home: ${returningTripText}`,
  );
  assert(
    returningTripText.includes(expectedRemainingText),
    `returning-trip/e2e: saved confirmed spend was not reflected on home; expected ${expectedRemainingText}: ${returningTripText}`,
  );
  assert(
    returningTripText.includes("does not refresh the FX rate automatically"),
    "returning-trip/e2e: home continuity omitted the no-auto-refresh trust boundary",
  );
  await assertNoHorizontalOverflow(page, "returning-trip/e2e");
  await assertAxe(page, "returning-trip/e2e");
}

async function assertReducedMotion(page, surface) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForFunction(
    () => document.getAnimations().every((animation) => animation.playState !== "running"),
    null,
    { timeout: 500 },
  );
  const state = await page.evaluate(() => ({
    matches: matchMedia("(prefers-reduced-motion: reduce)").matches,
    runningAnimations: document
      .getAnimations()
      .filter((animation) => animation.playState === "running").length,
  }));
  assert(state.matches, `${surface}: reduced-motion media emulation did not apply`);
  assert(
    state.runningAnimations === 0,
    `${surface}: ${state.runningAnimations} animation(s) still running in reduced-motion mode`,
  );
  await assertNoHorizontalOverflow(page, `${surface}/reduced-motion`);
}

async function assertForcedColors(page, surface) {
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  assert(
    await page.evaluate(() => matchMedia("(forced-colors: active)").matches),
    `${surface}: forced-colors media emulation did not apply`,
  );

  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  });
  // Establish keyboard modality first. Headless Chromium can otherwise treat a direct
  // programmatic focus after pointer-driven flows as not :focus-visible.
  await page.keyboard.press("Tab");
  const focusTarget =
    surface === "converter"
      ? page.locator("#workspace-amount")
      : surface === "current-converter"
        ? page.locator("#id_amount")
        : page.locator(".qa-skip-link");
  await focusTarget.focus();

  const focusState = await focusTarget.evaluate((element) => {
    const candidates = [
      element,
      element.closest(".qa-amount-control"),
      element.closest(".qa-selector-trigger"),
      element.closest(".qa-primary-button"),
      element.closest(".qa-swap-button"),
    ].filter(Boolean);

    return candidates.map((candidate) => {
      const style = getComputedStyle(candidate);
      return {
        outlineStyle: style.outlineStyle,
        outlineWidth: style.outlineWidth,
        boxShadow: style.boxShadow,
      };
    });
  });
  const hasVisibleFocus = focusState.some(
    (style) =>
      (style.outlineStyle !== "none" && style.outlineWidth !== "0px") || style.boxShadow !== "none",
  );
  assert(hasVisibleFocus, `${surface}: focus indicator disappears in forced-colors mode`);
  await assertNoHorizontalOverflow(page, `${surface}/forced-colors`);
}

async function prepareScreenshotState(page) {
  await page.emulateMedia({ forcedColors: "none", reducedMotion: "no-preference" });
  await page.evaluate(() => {
    document.documentElement.style.removeProperty("font-size");
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  });
  await waitForStableLayout(page);
}

async function assertTextExpansion(page, surface) {
  await page.emulateMedia({ forcedColors: "none", reducedMotion: "reduce" });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  await waitForStableLayout(page);
  await assertNoHorizontalOverflow(page, `${surface}/text-200`);

  const clippedInteractive = await page
    .locator("button, input, summary, a")
    .evaluateAll((elements) =>
      elements
        .filter((element) => {
          const style = getComputedStyle(element);
          return (
            element.clientWidth > 0 &&
            element.scrollWidth > element.clientWidth + 1 &&
            style.overflowX === "hidden"
          );
        })
        .map(
          (element) =>
            element.id || element.getAttribute("aria-label") || element.textContent?.trim(),
        )
        .filter(Boolean),
    );
  assert(
    clippedInteractive.length === 0,
    `${surface}: clipped interactive text after expansion: ${clippedInteractive.join(", ")}`,
  );
}

async function assertConverterTransitionLayout(page) {
  const workspace = page.locator(".qa-workspace");
  const source = page.locator(".qa-workspace__context--source");
  const destination = page.locator(".qa-workspace__context--destination");

  for (const state of [
    { width: 767, mode: "compact" },
    { width: 768, mode: "wide" },
    { width: 769, mode: "wide" },
  ]) {
    await workspace.evaluate((element, width) => {
      element.style.width = `${width}px`;
      element.style.maxWidth = "none";
    }, state.width);

    const sourceBox = await source.boundingBox();
    const destinationBox = await destination.boundingBox();
    assert(
      sourceBox && destinationBox,
      `converter/container-${state.width}: bilateral contexts are not measurable`,
    );

    if (state.mode === "compact") {
      assert(
        destinationBox.y > sourceBox.y + 2,
        `converter/container-${state.width}: expected compact stacked bilateral layout`,
      );
    } else {
      assert(
        Math.abs(destinationBox.y - sourceBox.y) <= 2,
        `converter/container-${state.width}: expected wide simultaneous bilateral layout`,
      );
    }
  }

  await workspace.evaluate((element) => {
    element.style.removeProperty("width");
    element.style.removeProperty("max-width");
  });
}

async function installLayoutShiftObserver(page) {
  await page.addInitScript(() => {
    window.__qaLayoutShiftScore = null;
    window.__qaLayoutShiftEntries = [];
    if (
      typeof PerformanceObserver === "undefined" ||
      !PerformanceObserver.supportedEntryTypes?.includes("layout-shift")
    ) {
      return;
    }

    const describeNode = (node) => {
      if (!(node instanceof Element)) return "unknown";
      if (node.id) return `#${node.id}`;
      const classes = [...node.classList].slice(0, 3);
      return `${node.tagName.toLowerCase()}${classes.map((name) => `.${name}`).join("")}`;
    };

    window.__qaLayoutShiftScore = 0;
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.hadRecentInput) continue;
        window.__qaLayoutShiftScore += entry.value;
        window.__qaLayoutShiftEntries.push({
          value: Math.round(entry.value * 10000) / 10000,
          sources: (entry.sources ?? []).map((source) => ({
            node: describeNode(source.node),
            previousRect: source.previousRect,
            currentRect: source.currentRect,
          })),
        });
      }
    });
    observer.observe({ type: "layout-shift", buffered: true });
    window.__qaLayoutShiftObserver = observer;
  });
}

async function collectPerformance(page) {
  return page.evaluate(() => {
    const resources = performance.getEntriesByType("resource");
    const applicationResources = resources.filter(
      (entry) => new URL(entry.name).pathname !== "/favicon.ico",
    );
    const sum = (entries, key) => entries.reduce((total, entry) => total + (entry[key] || 0), 0);
    const byExtension = (extension) =>
      applicationResources.filter((entry) => new URL(entry.name).pathname.endsWith(extension));
    const navigation = performance.getEntriesByType("navigation")[0];

    return {
      requestCount: applicationResources.length + (navigation ? 1 : 0),
      browserRequestCount: resources.length + (navigation ? 1 : 0),
      transferBytes: sum(applicationResources, "transferSize"),
      encodedBodyBytes: sum(applicationResources, "encodedBodySize"),
      jsEncodedBodyBytes: sum(byExtension(".js"), "encodedBodySize"),
      jsPaths: byExtension(".js").map((entry) => new URL(entry.name).pathname),
      cssEncodedBodyBytes: sum(byExtension(".css"), "encodedBodySize"),
      imageEncodedBodyBytes: applicationResources
        .filter((entry) => ["img", "image"].includes(entry.initiatorType))
        .reduce((total, entry) => total + (entry.encodedBodySize || 0), 0),
      layoutShiftScore:
        typeof window.__qaLayoutShiftScore === "number"
          ? Math.round(window.__qaLayoutShiftScore * 10000) / 10000
          : null,
      layoutShiftEntries: Array.isArray(window.__qaLayoutShiftEntries)
        ? window.__qaLayoutShiftEntries
        : [],
      domContentLoadedMs: navigation
        ? Math.round(navigation.domContentLoadedEventEnd - navigation.startTime)
        : null,
      loadMs: navigation ? Math.round(navigation.loadEventEnd - navigation.startTime) : null,
    };
  });
}

async function assertCspEnforcement(browser) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  try {
    const response = await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
    assert(response?.ok(), "csp/enforcement: converter request failed");
    await assertContentSecurityPolicyHeader(response, "csp/enforcement");

    const result = await page.evaluate(async () => {
      window.__qaInlineScriptExecuted = false;
      const violations = [];
      const listener = (event) => {
        violations.push({
          effectiveDirective: event.effectiveDirective,
          blockedURI: event.blockedURI,
        });
      };
      document.addEventListener("securitypolicyviolation", listener);

      const script = document.createElement("script");
      script.textContent = "window.__qaInlineScriptExecuted = true;";
      document.body.appendChild(script);

      await new Promise((resolve) => setTimeout(resolve, 100));
      document.removeEventListener("securitypolicyviolation", listener);

      return {
        inlineScriptExecuted: window.__qaInlineScriptExecuted,
        violations,
      };
    });

    assert(
      result.inlineScriptExecuted === false,
      "csp/enforcement: an injected inline script executed under enforced CSP",
    );
    assert(
      result.violations.some((violation) =>
        String(violation.effectiveDirective).startsWith("script-src"),
      ),
      `csp/enforcement: browser emitted no script CSP violation: ${JSON.stringify(result.violations)}`,
    );

    return {
      enforcedHeader: true,
      inlineScriptBlocked: true,
      violationEventObserved: true,
    };
  } finally {
    await context.close();
  }
}

async function assertNoJavaScriptSavedStateFallback(browser) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    javaScriptEnabled: false,
  });
  const page = await context.newPage();

  try {
    const converterUrl = new URL("/", BASE_URL);
    converterUrl.search = new URLSearchParams({
      convert: "1",
      amount: "12",
      source_country: "JP",
      source_currency: "JPY",
      destination_country: "JP",
      destination_currency: "JPY",
      rate_mode: "latest",
    }).toString();

    const converterResponse = await page.goto(converterUrl.toString(), {
      waitUntil: "networkidle",
    });
    assert(converterResponse?.ok(), "no-js converter deep link failed");
    await page.locator("#current-conversion-result").waitFor();

    const saveButton = page.locator("[data-save-pair]");
    assert(
      (await saveButton.count()) === 1,
      "no-js converter is missing the save enhancement marker",
    );
    assert(await saveButton.isHidden(), "no-js converter exposed an inert Save pair button");
    assert(
      await page
        .locator("#conversion-result-region")
        .getByRole("link", { name: "Saved & recent" })
        .isVisible(),
      "no-js converter should retain a path to the Saved & recent explanation",
    );

    const savedResponse = await page.goto(`${BASE_URL}/saved/`, { waitUntil: "networkidle" });
    assert(savedResponse?.ok(), "no-js Saved & recent page failed");
    const savedPageText = await page.locator("body").innerText();
    assert(
      savedPageText.includes(
        "JavaScript is required to read browser-local saved places, saved pairs and recent history.",
      ),
      "no-js Saved page did not expose the browser-local storage explanation",
    );
    assert(
      await page.locator("[data-favourites-empty]").isHidden(),
      "no-js Saved page falsely claimed that favourites were empty",
    );
    assert(
      await page.locator("[data-recents-empty]").isHidden(),
      "no-js Saved page falsely claimed that recent history was empty",
    );
    await assertNoHorizontalOverflow(page, "saved-state/no-js");

    return {
      converterResultRendered: true,
      inertSaveHidden: true,
      savedPageUnknownStateHonest: true,
    };
  } finally {
    await context.close();
  }
}

async function assertNoJavaScriptExplore(browser) {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    viewport: { width: 390, height: 844 },
  });
  try {
    const page = await context.newPage();
    const response = await page.goto(`${BASE_URL}/explore/`, { waitUntil: "load" });
    assert(
      response?.ok(),
      `explore/no-js: request failed with ${response?.status() ?? "no response"}`,
    );

    await page
      .getByRole("heading", { name: "Know the money before you know the place." })
      .waitFor();
    await page.getByRole("heading", { name: "Region → country → city." }).waitFor();
    assert(
      (await page.locator(".qa-explore-collection").count()) >= 4,
      "explore/no-js: curated collections disappeared without JavaScript",
    );
    assert(
      (await page.locator(".qa-explore-region-nav a").count()) >= 4,
      "explore/no-js: regional navigation disappeared without JavaScript",
    );
    assert(
      (await page.locator(".qa-explore-city-row").filter({ hasText: "Tokyo" }).count()) === 1,
      "explore/no-js: reviewed Tokyo city row disappeared without JavaScript",
    );
    assert(
      (await page.locator("[data-save-place]:visible").count()) === 0,
      "explore/no-js: browser-only save controls became visible without JavaScript",
    );
    const aiForm = page.locator(".qa-explore-ai__form");
    if ((await aiForm.count()) === 1) {
      assert(
        (await aiForm.getAttribute("action")) === "/explore/explain/",
        "explore/no-js: contextual AI form lost its standard POST fallback",
      );
      assert(
        (await aiForm.getByRole("button", { name: "What should I notice here?" }).count()) === 1,
        "explore/no-js: approved AI prompt disappeared without JavaScript",
      );
    }
    await assertNoHorizontalOverflow(page, "explore/no-js");
    return {
      collectionsVisible: true,
      regionalNavigationVisible: true,
      canonicalCityHandoffVisible: true,
    };
  } finally {
    await context.close();
  }
}

async function assertServerRenderedExploreAccessibility(browser) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const baseOrigin = new URL(BASE_URL).origin;
  await context.route("**/*", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    if (request.resourceType() === "script" && requestUrl.origin === baseOrigin) {
      await route.abort();
      return;
    }
    await route.continue();
  });

  try {
    const page = await context.newPage();
    const response = await page.goto(`${BASE_URL}/explore/`, { waitUntil: "load" });
    assert(
      response?.ok(),
      `explore/server-rendered-a11y: request failed with ${response?.status() ?? "no response"}`,
    );
    await page
      .getByRole("heading", { name: "Know the money before you know the place." })
      .waitFor();
    assert(
      (await page.locator(".qa-explore-collection").count()) >= 4,
      "explore/server-rendered-a11y: curated collections require application JavaScript",
    );
    await assertAxe(page, "explore/server-rendered-a11y");
    return {
      applicationScriptsBlocked: true,
      axePassed: true,
    };
  } finally {
    await context.close();
  }
}

async function assertPremiumResponsiveTargets(page, label, selector) {
  const originalViewport = page.viewportSize();
  for (const width of [430, 390, 360, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await waitForStableLayout(page);
    await assertNoHorizontalOverflow(page, `${label}/${width}`);

    const undersized = await page.locator(selector).evaluateAll((elements) =>
      elements
        .filter((element) => {
          const style = window.getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return (
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            rect.width > 0 &&
            rect.height > 0 &&
            rect.height < 44
          );
        })
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 80) ?? "",
            height: Math.round(rect.height * 10) / 10,
          };
        }),
    );
    assert(
      undersized.length === 0,
      `${label}/${width}: interactive targets below 44px: ${JSON.stringify(undersized)}`,
    );
  }

  if (originalViewport) {
    await page.setViewportSize(originalViewport);
    await waitForStableLayout(page);
  }
}

async function assertMoneyCultureStoryQuality(page) {
  await page
    .getByRole("heading", { name: "Currency history, without invented meaning.", exact: true })
    .waitFor();
  const story = page.locator(".qa-story-surface");
  await story
    .getByRole("heading", { name: "Which currency relationship applies here", exact: true })
    .waitFor();

  const eraCards = story.locator(".qa-story-era-card");
  assert(
    (await eraCards.count()) === 2,
    `money-culture-story: expected two canonical currency-era cards, found ${await eraCards.count()}`,
  );
  assert(
    (await story.getByText("Source currency era", { exact: true }).count()) === 1 &&
      (await story.getByText("Destination currency era", { exact: true }).count()) === 1,
    "money-culture-story: source/destination era identity is incomplete",
  );
  assert(
    (await story.locator(".qa-story-surface__scope").innerText()).includes(
      "Current reviewed context",
    ),
    "money-culture-story: current temporal scope is not explicit",
  );
  const storyText = await story.innerText();
  assert(
    /historical purchasing power/i.test(storyText),
    "money-culture-story: historical purchasing-power boundary is missing",
  );

  const sourceDetails = story.locator(".qa-story-source-details");
  for (const details of await sourceDetails.all()) {
    assert(
      !(await details.evaluate((element) => element.hasAttribute("open"))),
      "money-culture-story: provenance should be collapsed by default",
    );
    await details.locator("summary").click();
    assert(
      await details.evaluate((element) => element.hasAttribute("open")),
      "money-culture-story: provenance disclosure did not open",
    );
    assert(
      (await details.locator("a[href^='https://']").count()) > 0,
      "money-culture-story: provenance disclosure lost its HTTPS source",
    );
  }

  await assertPremiumResponsiveTargets(
    page,
    "money-culture-story/responsive",
    ".qa-story-page__actions a, .qa-story-source-details > summary",
  );
  await assertAxe(page, "money-culture-story/interactive");
}
async function assertHistoricalSeriesQuality(page) {
  await page.getByRole("heading", { name: "Historical trend surface", exact: true }).waitFor();

  const timeline = page.locator(".qa-rate-timeline");
  await timeline.getByRole("heading", { name: "Range anchors", exact: true }).waitFor();
  const landmarks = timeline.locator(".qa-rate-timeline__item");
  assert(
    (await landmarks.count()) >= 2,
    "rate-series: expected at least range-start and range-end timeline landmarks",
  );

  const dates = await timeline
    .locator("time")
    .evaluateAll((elements) => elements.map((element) => element.getAttribute("datetime") ?? ""));
  assert(
    dates.every((value, index) => index === 0 || value >= dates[index - 1]),
    `rate-series: timeline landmarks are not chronological: ${JSON.stringify(dates)}`,
  );
  assert(
    new Set(dates).size === dates.length,
    `rate-series: timeline duplicated an observation date: ${JSON.stringify(dates)}`,
  );
  assert(
    (await timeline.locator(".qa-rate-timeline__item.is-selected").count()) === 1,
    "rate-series: selected historical observation is not uniquely marked",
  );
  assert(
    (await timeline.getByText(/no historical purchasing-power inference/i).count()) === 1,
    "rate-series: historical FX boundary is missing from the timeline",
  );

  const periods = page.locator(".qa-chart-period-control");
  assert(
    (await periods.getByRole("link", { name: "1Y", exact: true }).count()) === 1 &&
      (await periods.getByRole("link", { name: "5Y", exact: true }).count()) === 1 &&
      (await periods.getByRole("link", { name: "10Y", exact: true }).count()) === 1,
    "rate-series: bounded period controls are incomplete",
  );
  assert(
    (await periods.getByRole("link", { name: "1Y", exact: true }).getAttribute("aria-current")) ===
      "page",
    "rate-series: active period is not exposed semantically",
  );

  const chart = page.locator("[data-rate-chart]");
  await chart.waitFor();
  await page.waitForFunction(
    () =>
      document.querySelector("[data-rate-chart]")?.getAttribute("data-rate-chart-enhanced") ===
      "true",
  );

  const table = page.locator(".qa-rate-series__table");
  assert(
    !(await table.evaluate((element) => element.hasAttribute("open"))),
    "rate-series: raw data table should be collapsed by default",
  );
  await table.locator("summary").click();
  assert(
    await table.evaluate((element) => element.hasAttribute("open")),
    "rate-series: raw data table did not open",
  );
  assert(
    (await table.locator("tbody tr").count()) > 0,
    "rate-series: opened raw data table has no published observations",
  );

  await assertPremiumResponsiveTargets(
    page,
    "rate-series/responsive",
    ".qa-chart-period-control__item, .qa-rate-series__custom > summary, .qa-rate-series__table > summary",
  );
  await assertAxe(page, "rate-series/interactive");
}
async function assertSameAmountQuality(page) {
  await page
    .getByRole("heading", { name: "One amount. Several places. No artificial winner." })
    .waitFor();

  const form = page.locator(".qa-same-amount__form");
  await form.locator('input[name="amount"]').fill("100");
  await form.locator('select[name="source_currency"]').selectOption("EUR");
  for (const destination of await form.locator('input[name="destinations"]').all()) {
    if (await destination.isChecked()) {
      await destination.uncheck();
    }
  }
  await form.locator('input[name="destinations"][value="FI:helsinki"]').check();
  await form.locator('input[name="destinations"][value="JP:tokyo"]').check();
  const selectedOrder = await form
    .locator('input[name="destinations"]:checked')
    .evaluateAll((elements) => elements.map((element) => element.value));

  const requestPromise = page.waitForRequest(
    (request) => request.url().endsWith("/explore/same-amount/") && request.method() === "POST",
  );
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/explore/same-amount/") && response.request().method() === "POST",
  );
  await form.getByRole("button", { name: "View across destinations", exact: true }).click();
  const [request, response] = await Promise.all([requestPromise, responsePromise]);
  assert(response.ok(), `same-amount: form submission returned ${response.status()}`);
  const submittedOrder = new URLSearchParams(request.postData() ?? "").getAll("destinations");
  assert(
    submittedOrder.length === 2,
    `same-amount: expected two submitted destinations, got ${JSON.stringify(submittedOrder)}`,
  );

  await page.getByRole("heading", { name: /across your selected destinations/ }).waitFor();
  const cards = page.locator(".qa-same-amount-card");
  assert(
    (await cards.count()) === 2,
    `same-amount: expected 2 result cards, found ${await cards.count()}`,
  );

  assert(
    JSON.stringify(selectedOrder) === JSON.stringify(["FI:helsinki", "JP:tokyo"]),
    `same-amount: deterministic checkbox selection drifted: ${JSON.stringify(selectedOrder)}`,
  );
  const renderedOrder = await cards.evaluateAll((elements) =>
    elements.map((element) => element.dataset.destinationToken ?? ""),
  );
  assert(
    JSON.stringify(renderedOrder) === JSON.stringify(submittedOrder),
    `same-amount: submitted destination order drifted: submitted=${JSON.stringify(submittedOrder)} rendered=${JSON.stringify(renderedOrder)}`,
  );
  assert(
    (await page.getByText("No winner is calculated.", { exact: true }).count()) === 1,
    "same-amount: neutral no-ranking boundary disappeared",
  );

  const availableCards = page.locator(
    ".qa-same-amount-card:not(.qa-same-amount-card--unavailable)",
  );
  const unavailableCards = page.locator(".qa-same-amount-card--unavailable");
  assert(
    (await availableCards.count()) > 0,
    "same-amount: expected at least one successful destination observation",
  );

  for (const card of await availableCards.all()) {
    assert(
      (await card.getByRole("link", { name: "Open conversion", exact: true }).count()) === 1,
      "same-amount: canonical conversion action is missing",
    );
    assert(
      (await card.getByRole("link", { name: "Build budget", exact: true }).count()) === 1,
      "same-amount: canonical budget action is missing",
    );
    assert(
      (await card.getByRole("link", { name: "City money profile", exact: true }).count()) === 1,
      "same-amount: city profile action is missing or duplicated",
    );
  }

  if ((await unavailableCards.count()) > 0) {
    assert(
      (await page.getByText("Part of the view is unavailable.", { exact: true }).count()) === 1,
      "same-amount: partial-result status disappeared",
    );
    for (const card of await unavailableCards.all()) {
      assert(
        (await card.locator(".qa-same-amount-card__amount").count()) === 0,
        "same-amount: unavailable destination must not display an inferred amount",
      );
      assert(
        (await card.getByText("Reference rate unavailable", { exact: true }).count()) === 1,
        "same-amount: unavailable destination lost its fail-closed explanation",
      );
    }
  }

  const context = availableCards.first().locator(".qa-same-amount-card__context");
  if ((await context.count()) === 1) {
    assert(
      !(await context.evaluate((element) => element.hasAttribute("open"))),
      "same-amount: reviewed local context should be collapsed by default",
    );
    await context.locator("summary").click();
    assert(
      await context.evaluate((element) => element.hasAttribute("open")),
      "same-amount: reviewed local context did not open",
    );
    assert(
      (await context.locator("a[href^='https://']").count()) > 0,
      "same-amount: opened local context lost provenance links",
    );
  }

  await assertPremiumResponsiveTargets(
    page,
    "same-amount/responsive",
    ".qa-same-amount-card__actions a, .qa-same-amount-card__context summary",
  );
  await assertAxe(page, "same-amount/interactive");
}
async function assertCityProfileQuality(page) {
  await page.getByRole("heading", { level: 1 }).waitFor();

  const priceCards = page.locator(".qa-city-profile__price-card");
  assert((await priceCards.count()) > 0, "city-profile: expected at least one reviewed price card");
  assert(
    (await page.locator(".qa-city-profile__hero-actions .qa-primary-button").count()) === 1,
    "city-profile: hero must expose exactly one primary action",
  );
  assert(
    (await page.locator(".qa-city-profile__hero-actions .qa-secondary-button").count()) <= 1,
    "city-profile: hero action hierarchy regressed into button soup",
  );

  const converterHref = await page
    .locator(".qa-city-profile__hero-actions .qa-primary-button")
    .getAttribute("href");
  assert(converterHref, "city-profile: canonical converter handoff is missing");
  const converterUrl = new URL(converterHref, BASE_URL);
  assert(
    converterUrl.searchParams.get("destination_country") === "JP" &&
      converterUrl.searchParams.get("destination_currency") === "JPY" &&
      converterUrl.searchParams.get("destination_city_slug") === "tokyo",
    `city-profile: converter handoff lost Tokyo scope: ${converterHref}`,
  );

  const compareHref = await page
    .locator(".qa-city-profile__hero-actions .qa-city-profile__text-action")
    .getAttribute("href");
  assert(compareHref, "city-profile: contextual Compare handoff is missing");
  const compareUrl = new URL(compareHref, BASE_URL);
  assert(
    compareUrl.pathname === "/compare/" &&
      compareUrl.searchParams.get("left_destination") === "JP:tokyo" &&
      !compareUrl.searchParams.has("right_destination"),
    `city-profile: Compare handoff lost canonical Tokyo scope: ${compareHref}`,
  );

  const evidence = priceCards.first().locator(".qa-city-profile__evidence");
  assert(
    !(await evidence.evaluate((element) => element.hasAttribute("open"))),
    "city-profile: provenance disclosure should be collapsed by default",
  );
  await evidence.locator("summary").click();
  assert(
    await evidence.evaluate((element) => element.hasAttribute("open")),
    "city-profile: provenance disclosure did not open",
  );
  assert(
    (await evidence.locator("a[href^='https://']").count()) === 1,
    "city-profile: provenance disclosure lost its canonical source link",
  );

  await assertPremiumResponsiveTargets(
    page,
    "city-profile/responsive",
    ".qa-city-profile__hero-actions a, .qa-city-profile__next-actions a, .qa-city-profile__evidence summary",
  );
  await assertAxe(page, "city-profile/interactive");
}
async function assertExploreFlow(page) {
  await page.getByRole("heading", { name: "Know the money before you know the place." }).waitFor();
  await page.getByRole("heading", { name: "Start with what matters to you." }).waitFor();
  await page.getByRole("heading", { name: "Region → country → city." }).waitFor();

  const jumpNav = page.locator(".qa-explore-jump-nav");
  assert(
    (await jumpNav.getByRole("link", { name: "Same amount", exact: true }).count()) === 1 &&
      (await jumpNav.getByRole("link", { name: "Curated collections", exact: true }).count()) ===
        1 &&
      (await jumpNav.getByRole("link", { name: "Regions & cities", exact: true }).count()) === 1,
    "explore: compact section navigation is incomplete",
  );

  const collectionCount = await page.locator(".qa-explore-collection").count();
  assert(
    collectionCount >= 4,
    `explore: expected at least four curated collections, found ${collectionCount}`,
  );

  const evidence = page.locator(".qa-explore-evidence").first();
  const evidenceSummary = evidence.locator("summary");
  assert(
    !(await evidence.evaluate((element) => element.hasAttribute("open"))),
    "explore: provenance disclosure should be collapsed by default",
  );
  await evidenceSummary.click();
  assert(
    await evidence.evaluate((element) => element.hasAttribute("open")),
    "explore: provenance disclosure did not open",
  );
  assert(
    (await evidence.locator("a[href^='https://']").count()) > 0,
    "explore: opened provenance disclosure has no HTTPS source",
  );

  const regionNav = page.locator(".qa-explore-region-nav");
  for (const region of ["Americas", "Asia", "Europe", "Oceania"]) {
    assert(
      (await regionNav.getByRole("link", { name: region, exact: true }).count()) === 1,
      `explore: missing regional navigation link for ${region}`,
    );
  }
  await regionNav.getByRole("link", { name: "Asia", exact: true }).click();
  assert(
    new URL(page.url()).hash === "#region-asia",
    "explore: region anchor did not update location",
  );

  const tokyoRow = page.locator(".qa-explore-city-row").filter({ hasText: "Tokyo" }).first();
  const profileHref = await tokyoRow.getByRole("link", { name: /Tokyo/ }).getAttribute("href");
  assert(profileHref === "/city/JP/tokyo/", `explore: Tokyo profile URL drifted: ${profileHref}`);

  const convertHref = await tokyoRow
    .getByRole("link", { name: "Convert", exact: true })
    .getAttribute("href");
  assert(convertHref, "explore: Tokyo direct Convert handoff is missing");
  const convertUrl = new URL(convertHref, BASE_URL);
  assert(
    convertUrl.searchParams.get("destination_country") === "JP" &&
      convertUrl.searchParams.get("destination_currency") === "JPY" &&
      convertUrl.searchParams.get("destination_city_slug") === "tokyo",
    `explore: Tokyo converter handoff lost canonical scope: ${convertHref}`,
  );

  const compareHref = await tokyoRow
    .getByRole("link", { name: "Compare", exact: true })
    .getAttribute("href");
  assert(compareHref, "explore: Tokyo contextual Compare handoff is missing");
  const compareUrl = new URL(compareHref, BASE_URL);
  assert(
    compareUrl.pathname === "/compare/" &&
      compareUrl.searchParams.get("left_destination") === "JP:tokyo" &&
      !compareUrl.searchParams.has("right_destination"),
    `explore: Tokyo Compare handoff lost canonical scope or over-selected a peer: ${compareHref}`,
  );

  const comparisonPage = await page.context().newPage();
  try {
    const comparisonResponse = await comparisonPage.goto(compareUrl.toString(), {
      waitUntil: "networkidle",
    });
    assert(
      comparisonResponse?.ok(),
      `explore/compare: seeded comparison returned ${comparisonResponse?.status() ?? "no response"}`,
    );
    await comparisonPage
      .getByText("Destination A is already selected.", { exact: false })
      .waitFor();
    assert(
      (await comparisonPage.locator('select[name="left_destination"]').inputValue()) === "JP:tokyo",
      "explore/compare: seeded Destination A was not preserved in the comparison form",
    );
    assert(
      (await comparisonPage.locator('select[name="right_destination"]').inputValue()) === "",
      "explore/compare: comparison handoff silently selected Destination B",
    );
    await assertNoHorizontalOverflow(comparisonPage, "explore/compare-handoff");
    await assertAxe(comparisonPage, "explore/compare-handoff");
  } finally {
    await comparisonPage.close();
  }

  const savePlace = tokyoRow.getByRole("button", {
    name: "Save place: Tokyo, Japan",
    exact: true,
  });
  await savePlace.waitFor();
  assert(
    (await savePlace.getAttribute("aria-pressed")) === "false",
    "explore: unsaved Tokyo did not expose an unpressed save toggle",
  );
  await savePlace.click();
  await page.waitForFunction((key) => {
    const state = JSON.parse(localStorage.getItem(key) ?? "{}");
    return state.places?.some((place) => place.token === "JP:tokyo") === true;
  }, LOCAL_STATE_KEY);
  const savedPlace = tokyoRow.getByRole("button", {
    name: "Remove saved place: Tokyo, Japan",
    exact: true,
  });
  await savedPlace.waitFor();
  assert(
    (await savedPlace.getAttribute("aria-pressed")) === "true" &&
      (await savedPlace.getAttribute("data-saved")) === "true",
    "explore: saved Tokyo did not expose a pressed saved state",
  );
  await tokyoRow.getByText("Place saved in this browser.", { exact: true }).waitFor();

  const aiSection = page.locator("#explore-ai");
  const collectionsSection = page.locator("#explore-collections");
  if ((await aiSection.count()) === 1) {
    const aiFollowsDeterministicContent = await page.evaluate(() => {
      const collections = document.getElementById("explore-collections");
      const ai = document.getElementById("explore-ai");
      return Boolean(
        collections &&
          ai &&
          collections.compareDocumentPosition(ai) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
    });
    assert(
      aiFollowsDeterministicContent,
      "explore: optional AI became more prominent than deterministic discovery",
    );
    assert(
      (await collectionsSection.count()) === 1,
      "explore: curated collections section is missing",
    );
  }

  const aiDestination = page.getByLabel("Reviewed destination", { exact: true });
  if ((await aiDestination.count()) === 1) {
    await aiDestination.selectOption("JP:tokyo");
    const overviewPrompt = page.getByRole("button", {
      name: "What should I notice here?",
      exact: true,
    });
    const aiResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/explore/explain/") && response.request().method() === "POST",
    );
    await overviewPrompt.click();
    const response = await aiResponse;
    assert(response.ok(), `explore/ai: explanation returned ${response.status()}`);

    const aiRegion = page.locator("#conversion-explanation-region");
    await aiRegion.locator('[data-ai-generated="true"]').waitFor();
    assert(
      (await aiRegion.innerText()).includes("Tokyo, Japan"),
      "explore/ai: response lost the selected reviewed destination",
    );
    assert(
      (await aiRegion.getAttribute("aria-busy")) === "false" &&
        (await aiRegion.getAttribute("data-ai-pending-requests")) === "0",
      "explore/ai: result region did not return to idle state",
    );
    assert(
      await aiRegion.evaluate((region) =>
        region.textContent
          ? !/cheapest|winner|best value|purchasing power|PPP/i.test(region.textContent)
          : true,
      ),
      "explore/ai: bounded answer introduced ranking or purchasing-power language",
    );
    assert(
      await page.evaluate(() =>
        document.activeElement?.matches(
          "#conversion-explanation-region [data-ai-explanation-focus]",
        ),
      ),
      "explore/ai: swapped explanation did not receive focus",
    );
  }

  await assertPremiumResponsiveTargets(
    page,
    "explore/responsive",
    ".qa-explore-jump-link, .qa-explore-region-nav a, .qa-explore-city-row .qa-saved-row__actions a, .qa-explore-city-row .qa-saved-row__actions button, .qa-explore-country > .qa-saved-row__actions a, .qa-explore-country > .qa-saved-row__actions button, .qa-explore-prompt",
  );
  await assertAxe(page, "explore/interactive");
}

async function assertDestinationComparisonQuality(page) {
  const form = page.locator(".qa-destination-comparison__form");
  await form.waitFor();

  await form.locator('input[name="amount"]').fill("500");
  await form.locator('select[name="source_currency"]').selectOption("EUR");
  await form.locator('select[name="left_destination"]').selectOption("JP:tokyo");
  await form.locator('select[name="right_destination"]').selectOption("NO");
  await form.locator("#id_duration_days").fill("3");
  await form.locator("#id_travelers").fill("1");

  const comparisonResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/compare/",
  );
  await form.getByRole("button", { name: "Compare destinations", exact: true }).click();
  const comparisonResponse = await comparisonResponsePromise;
  assert(
    comparisonResponse.status() === 200,
    `destination-comparison: comparison returned ${comparisonResponse.status()}`,
  );

  const results = page.locator(".qa-destination-comparison__results");
  await results.waitFor();
  await results.getByText("No winner is calculated.", { exact: true }).waitFor();
  const deterministicBeforeAi = await results
    .locator(".qa-destination-comparison__grid")
    .innerText();

  const aiRegion = page.locator("#comparison-explanation-region");
  const aiPrompt = page.getByRole("button", {
    name: "Explain this comparison",
    exact: true,
  });
  await aiPrompt.waitFor();
  const aiResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/compare/explain/",
  );
  await aiPrompt.click();
  const aiResponse = await aiResponsePromise;
  assert(
    aiResponse.status() === 200,
    `destination-comparison/ai: explanation returned ${aiResponse.status()}`,
  );
  await aiRegion.locator('[data-ai-generated="true"]').waitFor();
  assert(
    (await aiRegion.getAttribute("aria-busy")) === "false" &&
      (await aiRegion.getAttribute("data-ai-pending-requests")) === "0",
    "destination-comparison/ai: explanation region did not return to idle state",
  );
  assert(
    await page.evaluate(() =>
      document.activeElement?.matches("#comparison-explanation-region [data-ai-explanation-focus]"),
    ),
    "destination-comparison/ai: swapped explanation did not receive focus",
  );
  assert(
    (await results.locator(".qa-destination-comparison__grid").innerText()) ===
      deterministicBeforeAi,
    "destination-comparison/ai: explanation changed the deterministic comparison result",
  );
  assert(
    !/cheapest|best value|more affordable|less affordable|you should choose/i.test(
      (await aiRegion.innerText()) ?? "",
    ),
    "destination-comparison/ai: explanation introduced ranking or affordability language",
  );

  await assertNoHorizontalOverflow(page, "destination-comparison/interactive");
  await assertAxe(page, "destination-comparison/interactive");
}

async function assertConstrainedNetworkCoreFlow(browser) {
  if (BROWSER_ENGINE !== "chromium") return { applicable: false };

  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 180,
    downloadThroughput: 128 * 1024,
    uploadThroughput: 64 * 1024,
    connectionType: "cellular3g",
  });

  try {
    const url = new URL("/", BASE_URL);
    url.searchParams.set("convert", "1");
    url.searchParams.set("amount", "100");
    url.searchParams.set("source_country", "FI");
    url.searchParams.set("source_currency", "EUR");
    url.searchParams.set("destination_country", "JP");
    url.searchParams.set("destination_currency", "JPY");
    url.searchParams.set("rate_mode", "latest");

    const response = await page.goto(url.toString(), {
      waitUntil: "networkidle",
      timeout: 30_000,
    });
    assert(response?.ok(), "constrained-network: converter request failed");
    await page.locator("#current-conversion-result").waitFor();
    await page.getByText("17450 JPY", { exact: false }).first().waitFor();
    await assertNoHorizontalOverflow(page, "constrained-network/current-converter");
    await assertAxe(page, "constrained-network/current-converter");
    return {
      applicable: true,
      latencyMs: 180,
      downloadBytesPerSecond: 128 * 1024,
      uploadBytesPerSecond: 64 * 1024,
      conversionVisible: true,
    };
  } finally {
    await context.close();
  }
}

async function openSurface(page, surface) {
  const response = await page.goto(`${BASE_URL}${surface.path}`, { waitUntil: "networkidle" });
  await waitForStableLayout(page);
  assert(
    response?.ok(),
    `${surface.name}: request failed with ${response?.status() ?? "no response"}`,
  );
  await assertContentSecurityPolicyHeader(response, surface.name);
  const h1Count = await page.locator("h1").count();
  assert(h1Count === 1, `${surface.name}: expected exactly one H1, found ${h1Count}`);
  return response;
}

await mkdir(OUTPUT_DIR, { recursive: true });
const browser = await browserType.launch();
const activeSurfaces =
  BROWSER_SCOPE === "full"
    ? SURFACES
    : SURFACES.filter((surface) =>
        [
          "current-converter",
          "destination-mode",
          "destination-comparison",
          "explore",
          "city-money-profile",
          "money-culture-story",
          "saved-state",
          "rate-series",
        ].includes(surface.name),
      );
const activeViewports =
  BROWSER_SCOPE === "full"
    ? VIEWPORTS
    : VIEWPORTS.filter((viewport) => ["wide-1440", "mobile-390"].includes(viewport.name));
const evidence = {
  browserEngine: BROWSER_ENGINE,
  scope: BROWSER_SCOPE,
  generatedAt: new Date().toISOString(),
  surfaces: {},
  budgets: {
    ...PERFORMANCE_BUDGETS,
    source: PERFORMANCE_BUDGET_SOURCE,
  },
};

try {
  for (const surface of activeSurfaces) {
    evidence.surfaces[surface.name] = {};

    for (const viewport of activeViewports) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        deviceScaleFactor: 1,
      });
      const page = await context.newPage();
      await installLayoutShiftObserver(page);
      const consoleErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });

      await openSurface(page, surface);
      const initialPerformanceEvidence = await collectPerformance(page);
      assert(
        initialPerformanceEvidence.requestCount <= PERFORMANCE_BUDGETS.initialRequestCount,
        `${surface.name}/${viewport.name}: initial request count ${initialPerformanceEvidence.requestCount} exceeds ${PERFORMANCE_BUDGETS.initialRequestCount} request budget`,
      );
      if (BROWSER_ENGINE === "chromium" && initialPerformanceEvidence.layoutShiftScore !== null) {
        assert(
          initialPerformanceEvidence.layoutShiftScore <= PERFORMANCE_BUDGETS.initialLayoutShift,
          `${surface.name}/${viewport.name}: initial layout shift ${initialPerformanceEvidence.layoutShiftScore} exceeds ${PERFORMANCE_BUDGETS.initialLayoutShift} budget: ${JSON.stringify(initialPerformanceEvidence.layoutShiftEntries)}`,
        );
      }
      await assertNoHorizontalOverflow(page, `${surface.name}/${viewport.name}`);
      await assertKeyboardFocus(page, surface.name);

      if (viewport.name === "wide-1440" || viewport.name === "mobile-390") {
        await assertAxe(page, `${surface.name}/${viewport.name}`);
      }

      if (
        BROWSER_SCOPE === "full" &&
        surface.name === "converter" &&
        viewport.name === "wide-1440"
      ) {
        await assertConverterTransitionLayout(page);
      }

      if (
        surface.name === "current-converter" &&
        (viewport.name === "wide-1440" ||
          (BROWSER_SCOPE === "full" && viewport.name === "mobile-390"))
      ) {
        await assertCurrentConverterFlow(page, consoleErrors);
      }

      if (surface.name === "destination-comparison" && viewport.name === "wide-1440") {
        await assertDestinationComparisonQuality(page);
      }

      if (surface.name === "saved-state" && viewport.name === "wide-1440") {
        await assertSavedStateFlow(page);
      }

      if (surface.name === "explore" && viewport.name === "wide-1440") {
        await assertExploreFlow(page);
      }

      if (surface.name === "same-amount" && viewport.name === "wide-1440") {
        await assertSameAmountQuality(page);
      }

      if (surface.name === "city-money-profile" && viewport.name === "wide-1440") {
        await assertCityProfileQuality(page);
      }

      if (surface.name === "money-culture-story" && viewport.name === "wide-1440") {
        await assertMoneyCultureStoryQuality(page);
      }

      if (surface.name === "rate-series" && viewport.name === "wide-1440") {
        await assertHistoricalSeriesQuality(page);
      }

      if (viewport.name === "mobile-390") {
        await assertReducedMotion(page, surface.name);
        if (BROWSER_SCOPE === "full") {
          await assertForcedColors(page, surface.name);
        }
      }

      if (BROWSER_SCOPE === "full" && ["reflow-640", "reflow-320"].includes(viewport.name)) {
        await assertTextExpansion(page, `${surface.name}/${viewport.name}`);
      }

      assert(
        consoleErrors.length === 0,
        `${surface.name}/${viewport.name}: console errors: ${consoleErrors.join(" | ")}`,
      );

      const performanceEvidence = await collectPerformance(page);
      evidence.surfaces[surface.name][viewport.name] = {
        ...performanceEvidence,
        initial: initialPerformanceEvidence,
      };

      await prepareScreenshotState(page);
      await page.screenshot({
        path: resolve(OUTPUT_DIR, `${surface.name}-${viewport.name}.png`),
        fullPage: true,
      });

      if (
        BROWSER_SCOPE === "full" &&
        surface.name === "account-signup" &&
        viewport.name === "wide-1440"
      ) {
        await assertAuthenticatedRecentHistoryFlow(page);
        assert(
          consoleErrors.length === 0,
          `account-history/e2e: console errors: ${consoleErrors.join(" | ")}`,
        );
      }

      await context.close();
    }
  }

  if (BROWSER_SCOPE === "full") {
    evidence.csp = await assertCspEnforcement(browser);
    evidence.noJavaScript = await assertNoJavaScriptSavedStateFallback(browser);
    evidence.noJavaScriptExplore = await assertNoJavaScriptExplore(browser);
    evidence.serverRenderedExploreAccessibility =
      await assertServerRenderedExploreAccessibility(browser);
    evidence.constrainedNetwork = await assertConstrainedNetworkCoreFlow(browser);
    evidence.compressedAssets = await measureBuildAssets();
    assertBuildPerformanceBudgets(evidence.compressedAssets);

    const dynamicAssetNames = new Set(
      evidence.compressedAssets.dynamicFiles.map((file) => file.name),
    );
    const dynamicAssetsFromPaths = (paths) =>
      new Set(
        (paths ?? [])
          .map((path) => path.split("/").at(-1))
          .filter((name) => dynamicAssetNames.has(name)),
      );
    const requestedDynamicAssets = (surfaceName) =>
      new Set(
        Object.values(evidence.surfaces[surfaceName] ?? {}).flatMap((measurement) => [
          ...dynamicAssetsFromPaths(measurement.jsPaths ?? []),
        ]),
      );
    const initiallyRequestedDynamicAssets = (surfaceName) =>
      new Set(
        Object.values(evidence.surfaces[surfaceName] ?? {}).flatMap((measurement) => [
          ...dynamicAssetsFromPaths(measurement.initial?.jsPaths ?? []),
        ]),
      );

    for (const surfaceName of ["shell", "same-amount", "city-money-profile"]) {
      assert(
        requestedDynamicAssets(surfaceName).size === 0,
        `${surfaceName} unexpectedly loaded route-only dynamic JavaScript: ${JSON.stringify([
          ...requestedDynamicAssets(surfaceName),
        ])}`,
      );
    }

    for (const surfaceName of ["current-converter", "explore", "saved-state", "rate-series"]) {
      assert(
        requestedDynamicAssets(surfaceName).size > 0,
        `${surfaceName} did not load its demand-driven enhancement JavaScript`,
      );
    }

    assert(
      requestedDynamicAssets("current-converter").size >
        initiallyRequestedDynamicAssets("current-converter").size,
      "current converter did not defer result-only enhancements until after HTMX interaction",
    );
  }

  await writeFile(
    resolve(OUTPUT_DIR, `performance-evidence-${BROWSER_ENGINE}.json`),
    `${JSON.stringify(evidence, null, 2)}\n`,
    "utf8",
  );
} finally {
  await browser.close();
}
