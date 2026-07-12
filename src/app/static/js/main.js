// Entry point: the light/auto/dark theme switch and the shout example.
//
// CSS light-dark() does the actual theming (see css/theme.css): no data-theme
// on <html> means "follow the OS" (the Auto choice), an explicit data-theme
// forces one scheme. This script only owns the switch buttons and persists
// explicit choices.

const themeButtons = document.querySelectorAll("[data-theme-choice]");

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

// --- shout example ---------------------------------------------------------
//
// The template's example API round trip: POST the typed text to /api/shout
// and render the uppercased reply. Copy this shape for real endpoints.

const shoutForm = document.querySelector("#shout-form");
const shoutInput = document.querySelector("#shout-input");
const shoutButton = document.querySelector("#shout-form button");
const shoutOutput = document.querySelector("#shout-output");

shoutForm.addEventListener("submit", async (event) => {
  event.preventDefault(); // stay on the page instead of a full-page GET submit
  // One request at a time: overlapping submits could resolve out of order
  // and leave a stale reply on screen.
  shoutButton.disabled = true;
  try {
    const response = await fetch("/api/shout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: shoutInput.value }),
    });
    if (!response.ok) {
      throw new Error(`unexpected HTTP ${response.status}`);
    }
    shoutOutput.textContent = (await response.json()).text;
  } catch (error) {
    // Network failure or non-2xx - tell the user instead of failing silently,
    // and keep the real cause in the console for whoever is debugging.
    console.error("shout failed:", error);
    shoutOutput.textContent = "Something went wrong - please try again.";
  } finally {
    shoutButton.disabled = false;
  }
});
