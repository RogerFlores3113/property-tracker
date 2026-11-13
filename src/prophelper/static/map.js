// Property Helper map page. Leaflet is vendored (static/vendor/leaflet), never loaded from a CDN.
// The page puts its data in <script type="application/json" id="map-data"> (escaped by the server). This file only
// reads that JSON and builds the map with DOM calls and textContent: user text is never written as HTML.
// With JavaScript off, the page still shows every place in lists, so nothing here is required to use it.
(function () {
  "use strict";

  var MILE = 1609.344;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = text; }
    return e;
  }

  function readData() {
    var node = document.getElementById("map-data");
    if (!node) { return null; }
    try { return JSON.parse(node.textContent || "{}"); } catch (e) { return null; }
  }

  function pinIcon(p) {
    var wrap = el("span", "ph-pin pin-" + (/^(good|ok|low|none)$/.test(p.band) ? p.band : "none"));
    wrap.appendChild(el("span", "ph-pin-label", p.label));
    return window.L.divIcon({ className: "ph-pin-host", html: wrap, iconSize: null });
  }

  function anchorIcon(a) {
    var wrap = el("span", "ph-pin pin-anchor");
    wrap.appendChild(el("span", "ph-pin-label", "■ " + a.name));
    return window.L.divIcon({ className: "ph-pin-host", html: wrap, iconSize: null });
  }

  function placePopup(p) {
    var box = el("div", "ph-popup");
    var link = el("a", "", p.title);
    link.setAttribute("href", p.url);
    box.appendChild(link);
    box.appendChild(el("div", "fine", p.stage + (p.score === null ? ", no score yet" : ", score " + Math.round(p.score))));
    box.appendChild(el("div", "fine", "True monthly cost: " + p.label));
    return box;
  }

  function init() {
    var host = document.getElementById("map");
    var data = readData();
    if (!host || !data || !window.L) { return; }
    var L = window.L;
    var map = L.map(host, { center: data.center, zoom: 13, scrollWheelZoom: false });
    host.classList.add("map-ready");
    if (data.tiles) {
      L.tileLayer(data.tileUrl, { maxZoom: 19, attribution: data.attribution }).addTo(map);
    } else {
      host.classList.add("map-plain");
      map.attributionControl.setPrefix(false);
    }

    var bounds = [];
    (data.places || []).forEach(function (p) {
      var m = L.marker([p.lat, p.lng], { icon: pinIcon(p), title: p.title + ", " + p.label, riseOnHover: true });
      m.bindPopup(placePopup(p));
      m.addTo(map);
      bounds.push([p.lat, p.lng]);
    });
    (data.anchors || []).forEach(function (a) {
      var m = L.marker([a.lat, a.lng], { icon: anchorIcon(a), title: "Anchor: " + a.name, zIndexOffset: 500 });
      m.addTo(map);
      bounds.push([a.lat, a.lng]);
    });
    if (data.ring) {
      (data.ring.miles || []).forEach(function (mi) {
        var c = L.circle([data.ring.lat, data.ring.lng], { radius: mi * MILE, className: "ph-ring", weight: 1.5, fill: false, interactive: false });
        c.addTo(map);
        c.bindTooltip(mi + (mi === 1 ? " mile" : " miles"), { sticky: true });
      });
    }
    if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
    } else if (bounds.length === 1) {
      map.setView(bounds[0], 14);
    } else {
      map.setView(data.center, 4);
    }
    host.addEventListener("focusin", function () { map.scrollWheelZoom.enable(); });
    host.addEventListener("focusout", function () { map.scrollWheelZoom.disable(); });
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); } else { init(); }
})();
