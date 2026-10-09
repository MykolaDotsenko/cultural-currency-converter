type DetectedBarcode = { rawValue?: string };

type BarcodeDetectorInstance = {
  detect(source: HTMLVideoElement): Promise<DetectedBarcode[]>;
};

type BarcodeDetectorConstructor = new (options: { formats: string[] }) => BarcodeDetectorInstance;

type ScannerWindow = Window & {
  BarcodeDetector?: BarcodeDetectorConstructor;
};

const BARCODE_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];
const SCAN_INTERVAL_MS = 350;

function validBarcode(raw: string | undefined): raw is string {
  return Boolean(raw && /^[0-9]{7,14}$/.test(raw) && !/^0+$/.test(raw));
}

export function enhanceShoppingBarcodeScanner(): void {
  for (const root of document.querySelectorAll<HTMLFormElement>(
    "[data-shopping-barcode-scanner]",
  )) {
    if (root.dataset.shoppingScannerEnhanced === "true") continue;
    root.dataset.shoppingScannerEnhanced = "true";

    const input = root.querySelector<HTMLInputElement>("#shopping-barcode");
    const start = root.querySelector<HTMLButtonElement>("[data-shopping-scan-start]");
    const stop = root.querySelector<HTMLButtonElement>("[data-shopping-scan-stop]");
    const panel = root.querySelector<HTMLElement>("[data-shopping-scan-panel]");
    const video = root.querySelector<HTMLVideoElement>("[data-shopping-scan-video]");
    const status = root.querySelector<HTMLElement>("[data-shopping-scan-status]");
    if (!input || !start || !stop || !panel || !video || !status) continue;

    const detectorConstructor = (window as ScannerWindow).BarcodeDetector;
    if (
      !window.isSecureContext ||
      !navigator.mediaDevices?.getUserMedia ||
      !detectorConstructor
    ) {
      continue; // The manual GET lookup always remains fully functional.
    }

    const abortController = new AbortController();
    let stream: MediaStream | null = null;
    let scanTimeout: number | null = null;
    let generation = 0;

    const stopCamera = (): void => {
      generation += 1;
      if (scanTimeout !== null) window.clearTimeout(scanTimeout);
      scanTimeout = null;
      video.pause();
      video.srcObject = null;
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      panel.hidden = true;
      start.disabled = false;
    };

    const scan = async (detector: BarcodeDetectorInstance, token: number): Promise<void> => {
      if (generation !== token || !stream) return;
      try {
        const detections = await detector.detect(video);
        if (generation !== token || !stream) return;
        const code = detections.map((item) => item.rawValue).find(validBarcode);
        if (code) {
          stopCamera();
          input.value = code;
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.focus();
          status.textContent =
            "Barcode captured. Review the digits, then select Look up product.";
          return;
        }
      } catch {
        // Decoder may temporarily lack a usable frame. Never expose camera data
        // or interrupt manual Shopping input on a transient detection failure.
      }
      if (generation === token && stream) {
        scanTimeout = window.setTimeout(() => void scan(detector, token), SCAN_INTERVAL_MS);
      }
    };

    start.hidden = false;
    start.addEventListener(
      "click",
      async () => {
        const token = ++generation;
        start.disabled = true;
        status.textContent = "Requesting camera permission…";
        try {
          // This is only called from an explicit user click, never on page load.
          const acquired = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: { facingMode: { ideal: "environment" } },
          });
          if (generation !== token) {
            acquired.getTracks().forEach((track) => track.stop());
            return;
          }
          stream = acquired;
          panel.hidden = false;
          video.srcObject = acquired;
          await video.play();
          if (generation !== token) return;
          status.textContent = "Point the camera at a barcode. You can stop at any time.";
          const detector = new detectorConstructor({ formats: BARCODE_FORMATS });
          await scan(detector, token);
        } catch {
          if (generation !== token) return;
          stopCamera();
          status.textContent = "Camera unavailable or permission denied. Enter the code manually.";
        }
      },
      { signal: abortController.signal },
    );
    stop.addEventListener(
      "click",
      () => {
        stopCamera();
        status.textContent = "Camera stopped. You can enter a barcode manually.";
        input.focus();
      },
      { signal: abortController.signal },
    );
    document.addEventListener(
      "visibilitychange",
      () => {
        if (document.hidden) stopCamera();
      },
      { signal: abortController.signal },
    );
    window.addEventListener("pagehide", stopCamera, { signal: abortController.signal });
    document.addEventListener(
      "htmx:beforeCleanupElement",
      (event) => {
        const detail = (event as CustomEvent<{ elt?: Element }>).detail;
        const removed = detail?.elt ?? (event.target instanceof Element ? event.target : null);
        if (removed && (removed === root || removed.contains(root))) {
          stopCamera();
          abortController.abort();
        }
      },
      { signal: abortController.signal },
    );
  }
}
