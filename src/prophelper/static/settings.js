// Settings page: open the section a link points to (like /settings#resumes) even though sections start collapsed.
(function () {
  "use strict";
  function openFromHash() {
    var id = (location.hash || "").slice(1);
    if (!id) return;
    var el = document.getElementById(id);
    if (!el) return;
    var d = el.tagName === "DETAILS" ? el : el.closest("details");
    while (d) {
      d.open = true;
      d = d.parentElement ? d.parentElement.closest("details") : null;
    }
    el.scrollIntoView();
  }
  window.addEventListener("hashchange", openFromHash);
  openFromHash();
})();

// Colors: preview a theme or the light/dark choice as soon as it is picked. Save keeps it.
(function () {
  "use strict";
  var root = document.documentElement;
  document.querySelectorAll("input[data-theme-pick]").forEach(function (el) {
    el.addEventListener("change", function () { if (el.checked) root.setAttribute("data-theme", el.value); });
  });
  document.querySelectorAll("input[data-mode-pick]").forEach(function (el) {
    el.addEventListener("change", function () {
      if (!el.checked) return;
      if (el.value === "auto") root.removeAttribute("data-mode"); else root.setAttribute("data-mode", el.value);
    });
  });
})();
