// Property Helper app window. All page scripts live here so the Content-Security-Policy can forbid inline
// scripts. Pages opt in with data- attributes (add new ones below and document them here).
//   select[data-autosubmit]            submits its form when the choice changes (a <noscript> button is the fallback)
//   [data-board] / .kcard / .col-body  the board: drag a card to a column, filter box, hide closed, collapse columns
//   form[data-board-move]              the stage menu on a board card (moves the card, same as dragging)
//   form[data-bulk]                    the table's checkboxes and bulk bar (see table.js)
//   [data-parse-on-enter]              the Add page's link field: Enter reads the listing instead of saving
//   form[data-confirm] / button[data-confirm]  asks "Are you sure?" before a risky submit (also needs the tick box on the server)
// User text is only ever read with textContent / dataset and written with textContent, never innerHTML.
(function () {
  "use strict";

  function store(key, value) {  // localStorage can be blocked: remember things only when it works
    try {
      if (value === undefined) { return window.localStorage.getItem(key); }
      window.localStorage.setItem(key, value);
    } catch (e) { /* ignore */ }
    return null;
  }

  // HTMX: a server-rendered fragment replaces its target; never evaluate scripts from responses.
  document.addEventListener("DOMContentLoaded", function () {
    if (window.htmx && window.htmx.config) {
      window.htmx.config.allowScriptTags = false;
      window.htmx.config.allowEval = false;
      window.htmx.config.selfRequestsOnly = true;
      window.htmx.config.defaultSwapStyle = "innerHTML";
    }
    initAutosubmit();
    initFlashFocus();
    initBoard();
    initAdd();
    initConfirm();
  });

  // ---- after a save or reload, keyboard focus goes to the status line ("Saved", "Moved to Screen", the error)
  // unless the page already put focus somewhere on purpose (an autofocus box in a form that needs fixing)
  function initFlashFocus() {
    var active = document.activeElement;
    if (active && active !== document.body && active !== document.documentElement) { return; }
    var flash = document.querySelector("main .flash, .flash[role]");
    if (flash) { flash.focus(); }
  }

  // ---- selects that save when changed
  function initAutosubmit() {
    document.addEventListener("change", function (ev) {
      var el = ev.target;
      if (el && el.matches && el.matches("select[data-autosubmit]") && el.form && !el.form.hasAttribute("data-board-move")) {
        if (el.form.requestSubmit) { el.form.requestSubmit(); } else { el.form.submit(); }
      }
    });
  }

  // ---- board
  function initBoard() {
    var board = document.querySelector("[data-board]");
    if (!board) { return; }
    var status = document.getElementById("board-status");
    var filter = document.getElementById("board-filter");
    var hideClosed = document.getElementById("hide-closed");
    var dragged = null;

    function say(text) { if (status) { status.textContent = text; } }

    function recount() {
      board.querySelectorAll(".col").forEach(function (col) {
        var n = col.querySelectorAll(".kcard").length + (parseInt(col.dataset.hidden || "0", 10) || 0);
        var badge = col.querySelector("[data-count]");
        if (badge) { badge.textContent = String(n); }
      });
    }

    function applyFilter() {
      var q = (filter ? filter.value : "").trim().toLowerCase();
      var shown = 0;
      board.querySelectorAll(".kcard").forEach(function (card) {
        var match = !q || (card.dataset.search || "").indexOf(q) !== -1;
        card.hidden = !match;
        if (match) { shown += 1; }
      });
      var none = document.getElementById("no-match");
      if (none) { none.hidden = !(q && shown === 0); }
    }

    function csrfFree() { return { "HX-Request": "true" }; }

    // Move a card into a column right away, ask the server, and put it back if the server says no.
    function moveCard(card, stage, beforeNode) {
      var fromBody = card.parentNode;
      var next = card.nextSibling;
      var oldStage = card.dataset.stage;
      var body = board.querySelector('.col[data-stage="' + stage + '"] .col-body');
      if (!body || oldStage === stage) { return; }
      var footer = body.querySelector(".col-empty");
      body.insertBefore(card, beforeNode || footer);
      card.dataset.stage = stage;
      var select = card.querySelector("select");
      if (select) { select.value = stage; }
      recount();
      var company = (card.querySelector(".kcard-title") || {}).textContent || "Place";
      var data = new FormData();
      data.append("stage", stage);
      fetch("/places/" + encodeURIComponent(card.dataset.id) + "/stage", {
        method: "POST", body: data, headers: csrfFree(), credentials: "same-origin"
      }).then(function (resp) {
        if (resp.status === 409) {
          return resp.json().then(function (info) { var e = new Error("confirm"); e.confirmUrl = info.confirm_url; throw e; });
        }
        if (!resp.ok) { throw new Error("failed"); }
        return resp.json();
      }).then(function (info) {
        var days = card.querySelector("[data-days]");
        if (days) { days.textContent = info.days === 0 ? "Moved today" : info.days + " day" + (info.days === 1 ? "" : "s") + " in stage"; }
        say("Moved " + company + " to " + stage + "." + (info.note ? " " + info.note : ""));
      }).catch(function (err) {
        fromBody.insertBefore(card, next && next.parentNode === fromBody ? next : fromBody.querySelector(".col-empty"));
        card.dataset.stage = oldStage;
        if (select) { select.value = oldStage; }
        recount();
        if (err && err.confirmUrl) { window.location.href = err.confirmUrl; return; }  // final steps are confirmed on their own page
        say("Could not move " + company + ". It is back in " + oldStage + ".");
      });
    }

    board.addEventListener("dragstart", function (ev) {
      var card = ev.target.closest && ev.target.closest(".kcard");
      if (!card) { return; }
      dragged = card;
      card.classList.add("dragging");
      ev.dataTransfer.effectAllowed = "move";
      try { ev.dataTransfer.setData("text/plain", card.dataset.id); } catch (e) { /* ignore */ }
    });
    board.addEventListener("dragend", function () {
      if (dragged) { dragged.classList.remove("dragging"); }
      dragged = null;
      board.querySelectorAll(".over").forEach(function (el) { el.classList.remove("over"); });
    });
    board.addEventListener("dragover", function (ev) {
      var body = ev.target.closest && ev.target.closest("[data-drop]");
      if (!body || !dragged) { return; }
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      board.querySelectorAll(".over").forEach(function (el) { if (el !== body) { el.classList.remove("over"); } });
      body.classList.add("over");
    });
    board.addEventListener("drop", function (ev) {
      var body = ev.target.closest && ev.target.closest("[data-drop]");
      if (!body || !dragged) { return; }
      ev.preventDefault();
      body.classList.remove("over");
      var stage = body.closest(".col").dataset.stage;
      moveCard(dragged, stage, null);
    });

    // The stage menu on each card works with a keyboard and on touch screens.
    board.addEventListener("change", function (ev) {
      var select = ev.target;
      var form = select.closest && select.closest("form[data-board-move]");
      if (!form) { return; }
      ev.stopPropagation();
      var card = form.closest(".kcard");
      var oldStage = card.dataset.stage;
      if (select.value === oldStage) { return; }
      moveCard(card, select.value, null);
    });
    board.addEventListener("submit", function (ev) {
      if (ev.target.hasAttribute && ev.target.hasAttribute("data-board-move")) { ev.preventDefault(); }
    });

    // Collapse the closed columns
    board.querySelectorAll("[data-collapse]").forEach(function (btn) {
      var col = btn.closest(".col");
      var key = "board.collapsed." + col.dataset.stage;
      function set(collapsed) {
        col.classList.toggle("collapsed", collapsed);
        btn.textContent = collapsed ? "Expand" : "Collapse";
        btn.setAttribute("aria-label", (collapsed ? "Expand" : "Collapse") + " the " + col.dataset.stage + " column");
        btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      }
      // The closed columns (Passed, Closed) start collapsed; the choice is remembered once made.
      set(store(key) === null ? btn.hasAttribute("data-default-collapsed") : store(key) === "1");
      btn.addEventListener("click", function () {
        var collapsed = !col.classList.contains("collapsed");
        set(collapsed);
        store(key, collapsed ? "1" : "0");
      });
    });

    if (filter) { filter.addEventListener("input", applyFilter); }
    if (hideClosed) {
      hideClosed.checked = store("board.hideClosed") === "1";
      board.classList.toggle("hide-closed", hideClosed.checked);
      hideClosed.addEventListener("change", function () {
        board.classList.toggle("hide-closed", hideClosed.checked);
        store("board.hideClosed", hideClosed.checked ? "1" : "0");
      });
    }
  }

  // (the table's bulk actions live in table.js)

  // ---- ask before a risky submit (the server also needs the tick box, so this is only a courtesy)
  function initConfirm() {
    document.addEventListener("submit", function (ev) {
      var form = ev.target;
      var text = form && form.getAttribute && form.getAttribute("data-confirm");
      if (text && !window.confirm(text)) { ev.preventDefault(); }
    });
  }

  // ---- quick add
  function initAdd() {
    var url = document.querySelector("[data-parse-on-enter]");
    if (!url) { return; }
    // after the details are filled in, put the cursor in the first box that still needs typing
    document.body.addEventListener("htmx:afterSwap", function (ev) {
      var target = ev.detail && ev.detail.target;
      if (!target || target.id !== "add-fields") { return; }
      var f = target.querySelector("[autofocus]");
      if (f) { f.focus(); }
    });
    url.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        var btn = document.getElementById("parse-btn");
        if (btn && window.htmx) { window.htmx.trigger(btn, "click"); }
        else if (btn) { btn.click(); }
      }
    });
  }
})();
