// Apply before the stylesheet paints, including when this tab is reloaded.
const themeKey = "cdspeler-theme";
const themes = ["light", "dark", "christmas"];
const tvLayout = window.matchMedia?.("(min-width: 761px)");
const systemTheme = window.matchMedia?.("(prefers-color-scheme: dark)");
let themePreference = null;
const holidayKey = "cdspeler-holiday-effects";
let holidayEffects = true;
try {
  themePreference = localStorage.getItem(themeKey);
  holidayEffects = localStorage.getItem(holidayKey) !== "off";
} catch (_) {}
if (!themes.includes(themePreference)) themePreference = null;

const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
let hearthFailed = false;
let hearthRevision = 0;
function syncHearthVideo() {
  const video = document.getElementById("hearth-video");
  if (!video) return;
  const revision = ++hearthRevision;
  const active =
    document.documentElement.dataset.theme === "christmas" &&
    holidayEffects &&
    !reducedMotion?.matches &&
    !document.hidden &&
    !hearthFailed;
  if (!active) {
    video.pause();
    document.documentElement.dataset.hearthVideo = "off";
    return;
  }
  video.muted = true;
  if (!video.getAttribute("src")) video.src = video.dataset.src;
  const playing = video.play();
  playing
    ?.then(() => {
      if (revision !== hearthRevision) return;
      document.documentElement.dataset.hearthVideo = "on";
    })
    .catch(() => {
      if (revision !== hearthRevision) return;
      video.pause();
      document.documentElement.dataset.hearthVideo = "off";
    });
}
function applyTheme() {
  const preference =
    themePreference || (systemTheme?.matches ? "dark" : "light");
  const dark = preference === "dark" || preference === "christmas";
  const theme = dark ? (tvLayout?.matches ? "christmas" : "dark") : "light";
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.holidayEffects =
    theme === "christmas" && holidayEffects ? "on" : "off";
  const effectsButton = document.getElementById("holiday-effects");
  if (effectsButton) {
    effectsButton.setAttribute("aria-pressed", String(holidayEffects));
    const effectsLabel = holidayEffects
      ? "Kersteffecten uitzetten"
      : "Kersteffecten aanzetten";
    effectsButton.setAttribute("aria-label", effectsLabel);
    effectsButton.title = effectsLabel;
  }
  syncHearthVideo();
  const colors = { light: "#f1f0ec", dark: "#181816", christmas: "#14251f" };
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", colors[theme]);
  const button = document.getElementById("theme-toggle");
  if (button) {
    const labels = { light: "Licht", dark: "Donker", christmas: "Kerst" };
    const next =
      theme === "light" ? (tvLayout?.matches ? "christmas" : "dark") : "light";
    const label = `${labels[theme]} thema · ${labels[next].toLowerCase()} thema inschakelen`;
    button.removeAttribute("aria-pressed");
    button.setAttribute("aria-label", label);
    button.title = label;
  }
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme;
  themePreference = current === "light" ? "dark" : "light";
  try {
    localStorage.setItem(themeKey, themePreference);
  } catch (_) {}
  applyTheme();
}
applyTheme();
document.addEventListener("DOMContentLoaded", applyTheme);
systemTheme?.addEventListener("change", () => {
  if (!themePreference) applyTheme();
});
function toggleHolidayEffects() {
  holidayEffects = !holidayEffects;
  try {
    localStorage.setItem(holidayKey, holidayEffects ? "on" : "off");
  } catch (_) {}
  applyTheme();
}
window.addEventListener("storage", (event) => {
  if (event.key !== themeKey && event.key !== holidayKey && event.key !== null)
    return;
  if (event.key === themeKey || event.key === null)
    themePreference = themes.includes(event.newValue) ? event.newValue : null;
  if (event.key === holidayKey || event.key === null)
    holidayEffects = event.newValue !== "off";
  applyTheme();
});

tvLayout?.addEventListener("change", applyTheme);

reducedMotion?.addEventListener("change", syncHearthVideo);
document.addEventListener("visibilitychange", syncHearthVideo);
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("hearth-video")?.addEventListener("error", () => {
    hearthFailed = true;
    syncHearthVideo();
  });
});
