type TabId = "agent" | "dashboard";

const PLACEHOLDER_URLS: Record<TabId, string> = {
  agent: "placeholder://agent",
  dashboard: "placeholder://dashboard",
};

let selected: TabId = "agent";

function render(): void {
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((button) => {
    const active = button.dataset.tab === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const url = document.querySelector<HTMLElement>("#url");
  if (url) url.textContent = PLACEHOLDER_URLS[selected];
}

function selectTab(tab: TabId): void {
  selected = tab;
  render();
}

window.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((button) => {
    button.addEventListener("click", () => selectTab(button.dataset.tab as TabId));
  });
  render();
});
