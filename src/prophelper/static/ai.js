// Copy buttons for the AI panel. Any element with data-copy="#some-id" copies that element's text.
// Text areas copy their value; other elements copy their text. Links with data-copy copy first, then open.
(function () {
  "use strict";
  if (window.__aiCopyInit) return;
  window.__aiCopyInit = true;

  function textOf(node) {
    return node.tagName === "TEXTAREA" || node.tagName === "INPUT" ? node.value : node.textContent;
  }

  function fallbackCopy(text) {
    var box = document.createElement("textarea");
    box.value = text;
    box.setAttribute("readonly", "");
    box.style.position = "fixed";
    box.style.top = "-1000px";
    document.body.appendChild(box);
    box.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(box);
    return ok;
  }

  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return fallbackCopy(text); });
    }
    return Promise.resolve(fallbackCopy(text));
  }

  document.addEventListener("click", function (ev) {
    var button = ev.target.closest ? ev.target.closest("[data-copy]") : null;
    if (!button) return;
    var source = document.querySelector(button.getAttribute("data-copy"));
    if (!source) return;
    var isLink = button.tagName === "A";
    copy(textOf(source)).then(function (ok) {
      if (isLink) return;
      var original = button.getAttribute("data-label") || button.textContent;
      button.setAttribute("data-label", original);
      button.textContent = ok ? "Copied" : "Select the text and press Ctrl+C";
      window.setTimeout(function () { button.textContent = original; }, 2000);
    });
  });
})();
