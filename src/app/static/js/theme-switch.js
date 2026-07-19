// The light/auto/dark theme switch. One feature per module: this file (in
// templates/base.html, so every page gets it) and js/shout.js (in
// templates/index.html) load as separate <script type="module"> tags, so
// deleting one feature (markup and script tag) never breaks the other.
//
// CSS light-dark() does the actual theming (see css/theme.css): no data-theme
// on <html> means "follow the OS" (the Auto choice), an explicit data-theme
// forces one scheme. The native radios (see base.html) own the exclusivity,
// checked styling and keyboard behavior; this script only applies and
// persists choices.

const themeSwitch = document.querySelector(".theme-switch");
const themeRadios = themeSwitch.querySelectorAll("input[name='theme-choice']");

for (const radio of themeRadios) {
  // `change` fires only when the user selects an unchecked radio - re-picking
  // the current choice is a native no-op, and the programmatic sync below
  // doesn't fire it either.
  radio.addEventListener("change", () => {
    if (radio.value === "auto") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = radio.value;
    }
    // Persist only explicit choices - Auto clears the key, so the site goes
    // back to following prefers-color-scheme, exactly like a first visit.
    try {
      if (radio.value === "auto") {
        localStorage.removeItem("theme");
      } else {
        localStorage.setItem("theme", radio.value);
      }
    } catch {
      // Storage blocked: the choice simply won't survive a reload.
    }
  });
}

// Check the radio matching the current state - js/theme-init.js may have
// restored a saved choice before paint, which is why the markup hardcodes
// no `checked`.
const currentChoice = document.documentElement.dataset.theme ?? "auto";
for (const radio of themeRadios) {
  radio.checked = radio.value === currentChoice;
}

// The switch ships hidden (see base.html) - without JS it would be dead
// controls. Reveal it only now that the handlers above are wired.
themeSwitch.hidden = false;
