/* Civic Lens — interactive development map.
 * Renders every .map-canvas[data-src] from a GeoJSON FeatureCollection:
 *  - the full /map page (#map) gets filter controls + a count readout
 *  - per-meeting mini-maps (#meeting-map) are read-only and hide themselves when empty
 * MapLibre is self-hosted; vector tiles come from OpenFreeMap (allowed in the CSP).
 */
(function () {
  if (typeof maplibregl === 'undefined') return;

  var STYLE = 'https://tiles.openfreemap.org/styles/bright';
  var VEGAS = [-115.20, 36.12];
  var COLORS = { upcoming: '#976E1C', passed: '#2E6B4F', failed: '#99302C', decided: '#27326B' };
  var STATE_LABEL = { upcoming: 'Up for decision', passed: 'Approved', failed: 'Denied', decided: 'Action taken' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function colorExpr() {
    return ['match', ['get', 'state'],
      'upcoming', COLORS.upcoming, 'passed', COLORS.passed,
      'failed', COLORS.failed, COLORS.decided];
  }

  function popupHtml(p) {
    var bits = [];
    bits.push('<span class="mp-badge mp-' + esc(p.state) + '">' + esc(STATE_LABEL[p.state] || p.state) + '</span>');
    if (p.text) bits.push('<p class="mp-text">' + esc(p.text) + '</p>');
    var meta = [];
    if (p.where) meta.push(esc(p.where));
    if (p.zone) meta.push(esc(p.zone) + ' Zone');
    if (p.acres) meta.push(esc(p.acres) + ' acres');
    if (meta.length) bits.push('<p class="mp-meta">' + meta.join(' &middot; ') + '</p>');
    var sub = [];
    if (p.body_name) sub.push(esc(p.body_name));
    if (p.date) sub.push(esc(p.date));
    if (sub.length) bits.push('<p class="mp-sub">' + sub.join(' &middot; ') + '</p>');
    if (p.precision === 'area') bits.push('<p class="mp-approx">Approximate — neighborhood level</p>');
    if (p.url) bits.push('<a class="mp-link" href="' + esc(p.url) + '">Open meeting record &rarr;</a>');
    return '<div class="map-popup">' + bits.join('') + '</div>';
  }

  function boundsOf(features) {
    var b = new maplibregl.LngLatBounds();
    features.forEach(function (f) { b.extend(f.geometry.coordinates); });
    return b;
  }

  function fit(map, features) {
    if (!features.length) return;
    if (features.length === 1) {
      map.jumpTo({ center: features[0].geometry.coordinates, zoom: 13.5 });
    } else {
      map.fitBounds(boundsOf(features), { padding: 48, maxZoom: 14, duration: 0 });
    }
  }

  function initMap(el) {
    var src = el.getAttribute('data-src');
    var isMini = el.classList.contains('mini');
    var map = new maplibregl.Map({
      container: el,
      style: STYLE,
      center: VEGAS,
      zoom: isMini ? 10 : 9.2,
      attributionControl: { compact: true },
      cooperativeGestures: isMini   // don't hijack page scroll on embedded mini-maps
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

    var allFeatures = [];
    var ready = false;

    Promise.all([
      fetch(src).then(function (r) { return r.json(); }).catch(function () { return { features: [] }; }),
      new Promise(function (res) { map.on('load', res); })
    ]).then(function (out) {
      var gj = out[0] || { features: [] };
      allFeatures = gj.features || [];

      if (!allFeatures.length && isMini) {                 // nothing to show — remove the section
        var sec = el.closest('.meeting-map-sec');
        if (sec) sec.remove(); else el.remove();
        map.remove();
        return;
      }

      map.addSource('items', { type: 'geojson', data: gj });
      map.addLayer({
        id: 'items', type: 'circle', source: 'items',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 4.5, 12, 7, 15, 11],
          'circle-color': colorExpr(),
          'circle-opacity': ['case', ['==', ['get', 'precision'], 'area'], 0.16, 0.85],
          'circle-stroke-width': 2,
          'circle-stroke-color': ['case', ['==', ['get', 'precision'], 'area'], colorExpr(), '#FBF9F3'],
          'circle-stroke-opacity': 0.95
        }
      });
      ready = true;
      fit(map, allFeatures);

      var popup = new maplibregl.Popup({ closeButton: true, maxWidth: '300px', offset: 10 });
      map.on('click', 'items', function (e) {
        var f = e.features[0];
        popup.setLngLat(f.geometry.coordinates).setHTML(popupHtml(f.properties)).addTo(map);
        map.easeTo({ center: f.geometry.coordinates, duration: 350 });
      });
      map.on('mouseenter', 'items', function () { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'items', function () { map.getCanvas().style.cursor = ''; });

      if (!isMini) wireFilters(map, function () { return allFeatures; }, function () { return ready; });
    });

    return map;
  }

  function wireFilters(map, getFeatures, getReady) {
    var fb = document.getElementById('flt-body');
    var fs = document.getElementById('flt-status');
    var ft = document.getElementById('flt-topic');
    var countEl = document.getElementById('map-count');

    function matches(p, body, status, topic) {
      if (body && p.body !== body) return false;
      if (status === 'upcoming' && p.state !== 'upcoming') return false;
      if (status === 'decided' && p.state === 'upcoming') return false;
      if (topic && (p.topics || []).indexOf(topic) === -1) return false;
      return true;
    }

    function apply() {
      if (!getReady()) return;
      var body = fb ? fb.value : '';
      var status = fs ? fs.value : '';
      var topic = ft ? ft.value : '';

      var expr = ['all'];
      if (body) expr.push(['==', ['get', 'body'], body]);
      if (status === 'upcoming') expr.push(['==', ['get', 'state'], 'upcoming']);
      if (status === 'decided') expr.push(['!=', ['get', 'state'], 'upcoming']);
      if (topic) expr.push(['in', topic, ['get', 'topics']]);
      map.setFilter('items', expr.length > 1 ? expr : null);

      var all = getFeatures();
      var shown = all.filter(function (f) { return matches(f.properties, body, status, topic); });
      if (countEl) countEl.textContent = 'Showing ' + shown.length + ' of ' + all.length + ' items';
      if (shown.length) fit(map, shown);
    }

    [fb, fs, ft].forEach(function (el) { if (el) el.addEventListener('change', apply); });
    apply();
  }

  document.querySelectorAll('.map-canvas[data-src]').forEach(initMap);
})();
