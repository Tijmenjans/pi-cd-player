// Apply before the stylesheet paints, including when this tab is reloaded.
const themeKey = 'cdspeler-theme';
const themes = ['light', 'dark', 'christmas'];
const tvLayout = window.matchMedia?.('(min-width: 761px)');
const systemTheme = window.matchMedia?.('(prefers-color-scheme: dark)');
let themePreference = null;
try { themePreference = localStorage.getItem(themeKey); } catch (_) {}
if (!themes.includes(themePreference)) themePreference = null;

function applyTheme() {
  const preference = themePreference || (systemTheme?.matches ? 'dark' : 'light');
  const dark = preference === 'dark' || preference === 'christmas';
  const theme = dark ? (tvLayout?.matches ? 'christmas' : 'dark') : 'light';
  document.documentElement.dataset.theme = theme;
  const colors = {light:'#faf9f6', dark:'#151815', christmas:'#17251e'};
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', colors[theme]);
  const button = document.getElementById('theme-toggle');
  if (button) {
    const labels = {light:'Licht', dark:'Donker', christmas:'Kerst'};
    const next = theme === 'light' ? (tvLayout?.matches ? 'christmas' : 'dark') : 'light';
    const label = `${labels[theme]} thema · ${labels[next].toLowerCase()} thema inschakelen`;
    button.removeAttribute('aria-pressed');
    button.setAttribute('aria-label', label);
    button.title = label;
  }
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme;
  themePreference = current === 'light' ? 'dark' : 'light';
  try { localStorage.setItem(themeKey, themePreference); } catch (_) {}
  applyTheme();
}
applyTheme();
document.addEventListener('DOMContentLoaded', applyTheme);
systemTheme?.addEventListener('change', () => { if (!themePreference) applyTheme(); });
window.addEventListener('storage', event => {
  if (event.key !== themeKey && event.key !== null) return;
  themePreference = themes.includes(event.newValue) ? event.newValue : null;
  applyTheme();
});

tvLayout?.addEventListener('change', applyTheme);
