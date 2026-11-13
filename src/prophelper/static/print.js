// The "Print or save as PDF" button on the Compare page: opens the browser's print dialog (pick "Save as PDF" there).
(function () {
  "use strict";
  document.addEventListener("click", function (ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest("[data-print]") : null;
    if (el) { ev.preventDefault(); window.print(); }
  });
})();
