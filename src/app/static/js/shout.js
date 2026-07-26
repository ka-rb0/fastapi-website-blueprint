// The template's example API round trip: POST the typed text to the shout
// endpoint and render the uppercased reply. The endpoint is the form's
// action/method metadata (rendered server-side with url_for in
// templates/index.html), not a URL hardcoded here - so a deployment under a
// URL prefix (root_path) reaches the right route. Copy this shape for real
// endpoints - one feature per module, loaded by its own
// <script type="module"> tag in templates/index.html, so deleting it
// (markup and script tag) touches nothing else.

const shoutForm = document.querySelector("#shout-form");
const shoutInput = document.querySelector("#shout-input");
const shoutButton = shoutForm.querySelector("button[type=submit]");
const shoutOutput = document.querySelector("#shout-output");

shoutForm.addEventListener("submit", async (event) => {
  // Stay on the page: the native submission this replaces would be a
  // full-page form-encoded POST, which the JSON-only endpoint rejects.
  event.preventDefault();
  // One request at a time: overlapping submits could resolve out of order
  // and leave a stale reply on screen.
  shoutButton.disabled = true;
  try {
    // .action/.method resolve the form's rendered metadata to an absolute
    // URL and a fetch-normalizable method - the endpoint stays defined in
    // exactly one place, the server.
    const response = await fetch(shoutForm.action, {
      method: shoutForm.method,
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

// The form ships hidden (see templates/index.html) - without JS its native
// submission would hit the JSON-only endpoint with form-encoded data and land
// on a 422 error page. Reveal it only now that the handler above owns
// submission, the same pattern as the theme switch in js/theme-switch.js.
shoutForm.hidden = false;
