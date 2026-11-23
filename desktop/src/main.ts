import { invoke } from "@tauri-apps/api/core";

type TabId = "agent" | "dashboard";

let selected: TabId = "agent";

function tabFromUrl(url: string): TabId {
  try {
    const path = new URL(url).pathname.replace(/\/+$/, "") || "/";
    if (/^\/(en|ar)$/.test(path) || /\/agent-app(?:\/|$)/.test(path)) return "agent";
  } catch {
    /* ignore bad urls */
  }
  return "dashboard";
}

function render(url: string): void {
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((button) => {
    const active = button.dataset.tab === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const el = document.querySelector<HTMLElement>("#url");
  if (el) el.textContent = url;
}

async function selectTab(tab: TabId): Promise<void> {
  selected = tab;
  try {
    render(await invoke<string>("navigate_tab", { tab }));
  } catch (e) {
    render(`error: ${String(e)}`);
  }
}

// Content links (e.g. inside the dashboard) change the URL without the chrome knowing; keep tab + URL display in sync.
async function syncFromContent(): Promise<void> {
  const url = await invoke<string | null>("content_url").catch(() => null);
  if (!url || url === "about:blank") return;
  selected = tabFromUrl(url);
  render(url);
}

window.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((button) => {
    button.addEventListener("click", () => void selectTab(button.dataset.tab as TabId));
  });
  render("");
  window.setInterval(() => void syncFromContent(), 1000);
});
