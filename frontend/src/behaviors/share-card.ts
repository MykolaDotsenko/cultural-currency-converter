function sameOriginShareUrl(raw: string): string | null {
  try {
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin || url.pathname !== "/share/conversion/") return null;
    if (!url.searchParams.get("snapshot")) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function setStatus(root: HTMLElement, message: string, tone: string): void {
  const status = root.querySelector<HTMLElement>("[data-share-status]");
  if (!status) return;
  status.textContent = message;
  status.dataset.storageTone = tone;
}

async function copyShareUrl(root: HTMLElement, url: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
    } else {
      const input = root.querySelector<HTMLInputElement>("[data-share-url-input]");
      if (!input) throw new Error("copy fallback unavailable");
      input.focus();
      input.select();
      if (!document.execCommand("copy")) throw new Error("copy fallback failed");
    }
    setStatus(root, "Share link copied.", "feedback");
  } catch {
    setStatus(root, "Copy failed. Select the Share URL field and copy it manually.", "warning");
  }
}

export function enhanceShareCards(): void {
  for (const root of document.querySelectorAll<HTMLElement>("[data-share-card]")) {
    if (root.dataset.shareEnhanced === "true") continue;
    root.dataset.shareEnhanced = "true";

    const url = sameOriginShareUrl(root.dataset.shareUrl ?? "");
    if (!url) {
      setStatus(root, "Share link is unavailable.", "warning");
      continue;
    }

    const copyButton = root.querySelector<HTMLButtonElement>("[data-copy-share-link]");
    copyButton?.addEventListener("click", () => {
      void copyShareUrl(root, url);
    });

    const nativeButton = root.querySelector<HTMLButtonElement>("[data-native-share]");
    if (nativeButton && typeof navigator.share === "function") {
      nativeButton.hidden = false;
      nativeButton.addEventListener("click", () => {
        void navigator
          .share({
            title: root.dataset.shareTitle ?? "Cultural Currency",
            text: root.dataset.shareText ?? "",
            url,
          })
          .then(() => setStatus(root, "Shared.", "feedback"))
          .catch((error: unknown) => {
            if (error instanceof DOMException && error.name === "AbortError") return;
            setStatus(root, "Native sharing was unavailable. Copy the share link instead.", "warning");
          });
      });
    }
  }
}
