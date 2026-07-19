// The template's example API round trip: POST the typed text to /api/shout
// and render the uppercased reply. Copy this shape for real endpoints - one
// feature per module, loaded by its own <script type="module"> tag in
// index.html, so deleting it (markup and script tag) touches nothing else.

const shoutForm = document.querySelector("#shout-form");
const shoutInput = document.querySelector("#shout-input");
const shoutButton = shoutForm.querySelector("button[type=submit]");
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
