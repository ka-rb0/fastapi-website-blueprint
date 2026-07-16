// Re-apply a previously chosen theme before first paint to avoid a flash.
// Loaded as a classic blocking script in <head> on purpose: it must run
// before <body> renders. A separate file rather than an inline <script>
// because the CSP (see src/app/main.py) allows only same-origin script
// files - no inline scripts. Without a saved choice, data-theme stays unset
// and the CSS follows the OS scheme (see css/theme.css).
try {
  // Validate - a stale or corrupt value must not disable the switch.
  const saved = localStorage.getItem("theme");
  if (saved === "light" || saved === "dark") {
    document.documentElement.dataset.theme = saved;
  }
} catch {
  // Storage blocked - the CSS default (follow the OS) applies.
}
