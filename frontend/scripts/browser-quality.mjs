import { mkdir, writeFile } from "node:fs/promises";
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
  { name: "mobile-390", width: 390, height: 844 },
  { name: "reflow-320", width: 320, height: 700 },
];

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
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

async function assertAiExplanationReliability(page) {
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

  if (exerciseCancellation) {
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
  const generatedText = await region.innerText();
  assert(
    generatedText.includes("What does this reference rate mean?") &&
      generatedText.includes("What matters most") &&
      generatedText.includes("Watch out for") &&
      generatedText.includes("Next step"),
    `current-converter/ai: structured generated answer mismatch: ${JSON.stringify(generatedText)}`,
  );
  await page.waitForFunction(() =>
    document.getElementById("explanation-announcer")?.textContent?.includes("AI explanation ready."),
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
  await assertAiExplanationReliability(page);

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

  const sampleState = {
    version: 1,
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

  await page.getByRole("heading", { name: "EUR → JPY" }).waitFor();
  await page.getByText("100 EUR → 17450 JPY", { exact: true }).waitFor();
  await page.getByText("100 FIM → 21.35 USD", { exact: true }).waitFor();

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

  await page.locator("#id_spend_amount").fill("4700");
  await Promise.all([
    page.waitForURL((url) => /^\/saved\/scenarios\/\d+\/$/.test(url.pathname)),
    page.getByRole("button", { name: "Add spend" }).click(),
  ]);
  await page.getByText("Confirmed spend added to this saved budget.", { exact: true }).waitFor();

  const updatedSummary = await page
    .locator('[aria-labelledby="scenario-trip-budget-title"]')
    .innerText();
  assert(
    updatedSummary.includes("Confirmed spend 4700 JPY"),
    `trip-budget/e2e: confirmed spend did not update the saved budget: ${updatedSummary}`,
  );
  assert(
    !updatedSummary.includes("Confirmed spend 0 JPY"),
    "trip-budget/e2e: stale zero-spend state remained after confirmation",
  );
  const remainingMatch = updatedSummary.match(/([0-9]+(?:\.[0-9]+)?) JPY remaining/);
  assert(
    remainingMatch,
    `trip-budget/e2e: updated saved budget omitted remaining amount: ${updatedSummary}`,
  );
  const expectedRemainingText = `${remainingMatch[1]} JPY remaining`;
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
        "JavaScript is required to read browser-local saved pairs and recent history.",
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
          "destination-comparison",
          "explore",
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

      if (surface.name === "saved-state" && viewport.name === "wide-1440") {
        await assertSavedStateFlow(page);
      }

      if (viewport.name === "mobile-390") {
        await assertReducedMotion(page, surface.name);
        if (BROWSER_SCOPE === "full") {
          await assertForcedColors(page, surface.name);
        }
      }

      if (BROWSER_SCOPE === "full" && viewport.name === "reflow-320") {
        await assertTextExpansion(page, surface.name);
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
    evidence.compressedAssets = await measureBuildAssets();
    assertBuildPerformanceBudgets(evidence.compressedAssets);

    const dynamicAssetNames = new Set(
      evidence.compressedAssets.dynamicFiles.map((file) => file.name),
    );
    const requestedDynamicAssets = (surfaceName) =>
      new Set(
        Object.values(evidence.surfaces[surfaceName] ?? {})
          .flatMap((measurement) => measurement.jsPaths ?? [])
          .map((path) => path.split("/").at(-1))
          .filter((name) => dynamicAssetNames.has(name)),
      );

    assert(
      requestedDynamicAssets("current-converter").size === 0,
      "current converter unexpectedly loaded route-only dynamic JavaScript",
    );
    assert(
      requestedDynamicAssets("saved-state").size > 0,
      "saved-state surface did not load its route-specific renderer chunk",
    );
    assert(
      requestedDynamicAssets("rate-series").size > 0,
      "historical rate-series surface did not load its dynamic chart JavaScript chunk",
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
