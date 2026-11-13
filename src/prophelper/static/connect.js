// Connect an AI app page: "Copy" buttons, the app picker, and focus after a result is shown.
// Text comes from the element's textContent, never as markup.
(function () {
  "use strict";
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest ? ev.target.closest("button[data-copy]") : null;
    if (!btn) return;
    var src = document.getElementById(btn.getAttribute("data-copy"));
    if (!src || !navigator.clipboard) return;
    navigator.clipboard.writeText(src.textContent.trim()).then(function () {
      var old = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = old; }, 1500);
    });
  });

  // "Which AI app do you use?": show only that app's card (everything stays visible without JavaScript).
  document.addEventListener("click", function (ev) {
    var pick = ev.target.closest ? ev.target.closest("button[data-pick]") : null;
    if (!pick) return;
    var want = pick.getAttribute("data-pick");
    document.querySelectorAll("button[data-pick]").forEach(function (b) {
      b.setAttribute("aria-pressed", b === pick ? "true" : "false");
    });
    document.querySelectorAll(".app-card").forEach(function (card) {
      var app = card.getAttribute("data-app");
      card.hidden = !(want === "all" || app === want);
    });
    var other = document.getElementById("other-apps");
    if (other && want !== "all" && want !== "claude" && want !== "chatgpt") other.open = true;
  });

  // A link to a card inside a closed fold (like "I use ChatGPT") opens the fold first, then jumps to the card.
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest ? ev.target.closest('a[href^="#"]') : null;
    if (!a || a.getAttribute("href").length < 2) return;
    var target = document.getElementById(a.getAttribute("href").slice(1));
    if (!target) return;
    var fold = target.closest ? target.closest("details") : null;
    while (fold) { fold.open = true; fold = fold.parentElement ? fold.parentElement.closest("details") : null; }
    if (target.hidden) target.hidden = false;
    ev.preventDefault();
    target.scrollIntoView({ block: "start" });
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.focus();
  });

  // A "Cancel" on a preview removes it.
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest ? ev.target.closest("button[data-dismiss]") : null;
    if (!b) return;
    var box = b.closest(b.getAttribute("data-dismiss"));
    if (box) box.remove();
  });

  // After a result is swapped in, put keyboard focus on it so a screen reader reads it.
  document.body.addEventListener("htmx:afterSwap", function (ev) {
    var t = ev.detail && ev.detail.target;
    var f = t && t.querySelector ? t.querySelector("[data-focus]") : null;
    if (f) f.focus();
  });
})();
