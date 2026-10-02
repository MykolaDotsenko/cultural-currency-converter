import {
  assertBuildPerformanceBudgets,
  measureBuildAssets,
  PERFORMANCE_BUDGETS,
} from "./performance-budgets.mjs";

const evidence = await measureBuildAssets();
assertBuildPerformanceBudgets(evidence);

console.log(
  JSON.stringify(
    {
      budgets: PERFORMANCE_BUDGETS,
      measured: {
        coreJavaScriptGzipBytes: evidence.coreGzipBytes,
        totalJavaScriptGzipBytes: evidence.totalJavaScriptGzipBytes,
        stylesheetGzipBytes: evidence.stylesheetGzipBytes,
        rateChartGzipBytes: evidence.namedDynamicFiles.rateChart.gzipBytes,
        localSavedStateGzipBytes: evidence.namedDynamicFiles.localSavedState.gzipBytes,
      },
    },
    null,
    2,
  ),
);
