import { readdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { gzipSync } from "node:zlib";

const BUILD_ASSET_DIR = resolve(process.cwd(), "../static/build/assets");
const BUILD_MANIFEST_PATH = resolve(process.cwd(), "../static/build/.vite/manifest.json");
const VITE_ENTRY = "frontend/src/app.ts";

export const PERFORMANCE_BUDGETS = Object.freeze({
  coreJavaScriptGzipBytes: 32 * 1024,
  totalJavaScriptGzipBytes: 96 * 1024,
  stylesheetGzipBytes: 16 * 1024,
  rateChartGzipBytes: 64 * 1024,
  savedStateGzipBytes: 8 * 1024,
  initialRequestCount: 5,
});

export const PERFORMANCE_BUDGET_SOURCE = "docs/07_QUALITY_SECURITY_ACCESSIBILITY.md";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function measureFiles(names, loadingClass) {
  const files = [];
  for (const name of names) {
    const bytes = await readFile(resolve(BUILD_ASSET_DIR, name));
    files.push({
      name,
      rawBytes: bytes.length,
      gzipBytes: gzipSync(bytes, { level: 9 }).length,
      ...(loadingClass ? { loadingClass: loadingClass(name) } : {}),
    });
  }
  return files;
}

function total(files, key) {
  return files.reduce((sum, file) => sum + file[key], 0);
}

function uniquePrefixedAsset(files, prefix, label) {
  const matches = files.filter((file) => file.name.startsWith(prefix));
  assert(matches.length === 1, `expected one ${label} asset, found ${matches.length}`);
  return matches[0];
}

export async function measureBuildAssets() {
  const names = await readdir(BUILD_ASSET_DIR);
  const javascriptNames = names.filter((name) => name.endsWith(".js")).sort();
  const stylesheetNames = names.filter((name) => name.endsWith(".css")).sort();

  assert(javascriptNames.length > 0, "production build contains no JavaScript assets to measure");
  assert(stylesheetNames.length > 0, "production build contains no stylesheet assets to measure");

  const manifest = JSON.parse(await readFile(BUILD_MANIFEST_PATH, "utf8"));
  const entry = manifest[VITE_ENTRY];
  assert(entry?.file, `Vite manifest entry ${VITE_ENTRY} is missing`);

  const coreManifestKeys = new Set();
  const visitStaticImports = (key) => {
    if (coreManifestKeys.has(key)) return;
    const item = manifest[key];
    assert(item?.file, `Vite manifest static import ${key} is missing`);
    coreManifestKeys.add(key);
    for (const imported of item.imports ?? []) visitStaticImports(imported);
  };
  visitStaticImports(VITE_ENTRY);

  const coreAssetNames = new Set(
    [...coreManifestKeys]
      .map((key) => manifest[key]?.file)
      .filter((file) => typeof file === "string" && file.endsWith(".js"))
      .map((file) => file.split("/").at(-1)),
  );

  const javascript = await measureFiles(javascriptNames, (name) =>
    coreAssetNames.has(name) ? "core" : "dynamic",
  );
  const stylesheets = await measureFiles(stylesheetNames);
  const coreFiles = javascript.filter((file) => file.loadingClass === "core");
  const dynamicFiles = javascript.filter((file) => file.loadingClass === "dynamic");

  return {
    files: javascript,
    javascript,
    stylesheets,
    coreFiles,
    dynamicFiles,
    namedDynamicFiles: {
      savedState: uniquePrefixedAsset(dynamicFiles, "local-saved-state-page-", "saved-state"),
      rateChart: uniquePrefixedAsset(dynamicFiles, "rate-chart-", "rate-chart"),
    },
    coreRawBytes: total(coreFiles, "rawBytes"),
    coreGzipBytes: total(coreFiles, "gzipBytes"),
    dynamicRawBytes: total(dynamicFiles, "rawBytes"),
    dynamicGzipBytes: total(dynamicFiles, "gzipBytes"),
    totalJavaScriptRawBytes: total(javascript, "rawBytes"),
    totalJavaScriptGzipBytes: total(javascript, "gzipBytes"),
    totalRawBytes: total(javascript, "rawBytes"),
    totalGzipBytes: total(javascript, "gzipBytes"),
    stylesheetRawBytes: total(stylesheets, "rawBytes"),
    stylesheetGzipBytes: total(stylesheets, "gzipBytes"),
  };
}

export function assertBuildPerformanceBudgets(evidence, budgets = PERFORMANCE_BUDGETS) {
  const checks = [
    ["core JavaScript gzip", evidence.coreGzipBytes, budgets.coreJavaScriptGzipBytes],
    ["total JavaScript gzip", evidence.totalJavaScriptGzipBytes, budgets.totalJavaScriptGzipBytes],
    ["stylesheet gzip", evidence.stylesheetGzipBytes, budgets.stylesheetGzipBytes],
    [
      "rate-chart chunk gzip",
      evidence.namedDynamicFiles.rateChart.gzipBytes,
      budgets.rateChartGzipBytes,
    ],
    [
      "saved-state chunk gzip",
      evidence.namedDynamicFiles.savedState.gzipBytes,
      budgets.savedStateGzipBytes,
    ],
  ];

  for (const [label, actual, limit] of checks) {
    assert(actual <= limit, `${label} ${actual} B exceeds ${limit} B budget`);
  }
}
