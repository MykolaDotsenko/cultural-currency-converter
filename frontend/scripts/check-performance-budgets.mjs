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
        savedStateGzipBytes: evidence.namedDynamicFiles.savedState.gzipBytes,
      },
    },
    null,
    2,
  ),
);
