// The light/auto/dark theme switch. One feature per module: this file (in
// templates/base.html, so every page gets it) and js/shout.js (in
// templates/index.html) load as separate <script type="module"> tags, so
// deleting one feature (markup and script tag) never breaks the other.
//
// CSS light-dark() does the actual theming (see css/theme.css): no data-theme
// on <html> means "follow the OS" (the Auto choice), an explicit data-theme
// forces one scheme. This script only owns the switch buttons and persists
// explicit choices.

const themeSwitch = document.querySelector(".theme-switch");
const themeButtons = themeSwitch.querySelectorAll("[data-theme-choice]");

function selectedChoice() {
  return document.documentElement.dataset.theme ?? "auto";
}

function syncButtons() {
  for (const button of themeButtons) {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.themeChoice === selectedChoice()),
    );
  }
}

for (const button of themeButtons) {
  button.addEventListener("click", () => {
    const choice = button.dataset.themeChoice;
    if (choice === "auto") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = choice;
    }
    syncButtons();
    // Persist only explicit choices - Auto clears the key, so the site goes
    // back to following prefers-color-scheme, exactly like a first visit.
    try {
      if (choice === "auto") {
        localStorage.removeItem("theme");
      } else {
        localStorage.setItem("theme", choice);
      }
    } catch {
      // Storage blocked: the choice simply won't survive a reload.
    }
  });
}

syncButtons();
// The switch ships hidden (see index.html) - without JS it would be dead
// buttons. Reveal it only now that the handlers above are wired.
themeSwitch.hidden = false;
