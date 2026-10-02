import { enhanceCurrentConverterBehavior } from "./current-converter";
import { enhanceCurrentConverter } from "./picker";

export function enhanceConverterSurface(): void {
  enhanceCurrentConverterBehavior();
  enhanceCurrentConverter();
}
