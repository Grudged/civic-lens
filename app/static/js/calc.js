/* Civic Lens — "who represents this address?" calculator.
 *
 * Reads the form on /map, geocodes via /api/districts?address=…, renders the
 * matched reps in an editorial column, and (when MapLibre is available)
 * overlays the matched-district polygons + an address marker on the existing
 * land-use map. Falls back to a plain rep list when the map isn't loaded.
 *
 * No framework, no build step — same plain-JS pattern as map.js / countdown.js.
 */
(function () {
  var form = document.getElementById('calc-form');
  if (!form) return;
  var input = document.getElementById('calc-input');
  var statusEl = document.getElementById('calc-status');
  var resultsEl = document.getElementById('calc-results');
  var submitBtn = form.querySelector('.calc-submit');

  // Match the existing map.js newsprint palette.
  var LAYER_STROKE = '#27326B';   // ballot indigo
  var LAYER_FILL   = '#27326B';
  var MATCHED_STROKE = '#976E1C'; // civic brass for the layer the address falls in

  // We overlay only the polygons the address actually fell in (one per layer
  // when present), built from the geometries the API returns inline. No
  // second fetch, no client-side filtering of the full statewide set.
  var marker = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function setStatus(msg, kind) {
    statusEl.textContent = msg || '';
    statusEl.className = 'calc-status' + (kind ? ' is-' + kind : '');
  }

  function partyTag(p) {
    if (!p) return '';
    var cls = 'is-' + p.toLowerCase().replace(/[^a-z]/g, '');
    return '<span class="party-tag ' + cls + '">' + esc(p) + '</span>';
  }

  function repCard(d) {
    var rep = d.rep;
    var hasDistrict = !!d.district;
    var distHtml = hasDistrict
      ? '<p class="rep-district">District ' + esc(d.district) + '</p>'
      : '<p class="rep-district rep-district-empty">No matching district</p>';

    if (!rep) {
      // We know the district but don't have a rep seeded — be honest about it.
      return (
        '<li class="rep">' +
          '<div class="rep-photo placeholder" aria-hidden="true"></div>' +
          '<div class="rep-body">' +
            '<p class="rep-layer">' + esc(d.label) + '</p>' +
            distHtml +
            (hasDistrict ? '<p class="rep-meta muted">Representative not yet on file.</p>' : '') +
          '</div>' +
        '</li>'
      );
    }

    var photo = rep.photo_url
      ? '<img class="rep-photo" data-fallback="1" src="' + esc(rep.photo_url) + '" alt="" loading="lazy" referrerpolicy="no-referrer"/>'
      : '<div class="rep-photo placeholder" aria-hidden="true"></div>';

    var nameHtml = rep.profile_url
      ? '<a href="' + esc(rep.profile_url) + '" target="_blank" rel="noopener">' + esc(rep.full_name) + '</a>'
      : esc(rep.full_name);

    var meta = [];
    if (rep.term_ends) meta.push('Term ends ' + esc(rep.term_ends));
    if (rep.role) meta.push(esc(rep.role));

    var contacts = [];
    if (rep.contact_email) contacts.push('<a href="mailto:' + esc(rep.contact_email) + '">' + esc(rep.contact_email) + '</a>');
    if (rep.contact_phone) contacts.push('<span>' + esc(rep.contact_phone) + '</span>');

    var votes = '';
    if (d.recent_votes && d.recent_votes.length) {
      votes = '<details class="rep-votes"><summary>Recent votes (' + d.recent_votes.length + ')</summary><ul>' +
        d.recent_votes.map(function (v) {
          var stamp = v.vote ? '<span class="vote-stamp">' + esc(v.vote) + '</span>' : '';
          return '<li>' + stamp + ' <a href="/meeting/' + esc(v.event_id) + '">' + esc(v.title || 'Agenda item') + '</a>' +
            (v.meeting_date ? ' <span class="muted">— ' + esc((v.meeting_date || '').slice(0,10)) + '</span>' : '') + '</li>';
        }).join('') + '</ul></details>';
    }

    return (
      '<li class="rep">' +
        photo +
        '<div class="rep-body">' +
          '<p class="rep-layer">' + esc(d.label) + '</p>' +
          distHtml +
          '<p class="rep-name">' + nameHtml + ' ' + partyTag(rep.party) + '</p>' +
          (meta.length ? '<p class="rep-meta muted">' + meta.join(' · ') + '</p>' : '') +
          (contacts.length ? '<p class="rep-contact">' + contacts.join(' · ') + '</p>' : '') +
          votes +
        '</div>' +
      '</li>'
    );
  }

  function render(payload) {
    var geo = payload.geocoded;
    var districts = payload.districts || [];

    // Districts summary — a roster-style at-a-glance list of every district
    // the address falls in, before the user has to scan rep cards. The
    // district values use the same italic-serif treatment as the per-rep card.
    var summary = '';
    if (districts.length) {
      summary = '<div class="calc-summary">' +
        '<p class="kicker">Your districts</p>' +
        '<ul class="summary-list">' +
        districts.map(function (d) {
          var label = '<span class="sum-layer">' + esc(d.label) + '</span>';
          var distHtml = d.district
            ? '<span class="sum-dist">District ' + esc(d.district) + '</span>'
            : '<span class="sum-dist sum-dist-empty">no match</span>';
          return '<li>' + label + distHtml + '</li>';
        }).join('') +
        '</ul></div>';
    }

    var matched = '';
    if (geo && geo.matched_address) {
      matched = '<p class="calc-matched"><span class="kicker">Matched address</span> ' + esc(geo.matched_address) + '</p>';
    }
    var list = '<ul class="rep-list">' + districts.map(repCard).join('') + '</ul>';
    resultsEl.innerHTML = summary + matched + list;
    resultsEl.hidden = false;

    // CSP forbids inline onerror handlers; wire fallback to the placeholder
    // class here so broken photo URLs degrade gracefully.
    resultsEl.querySelectorAll('img.rep-photo[data-fallback]').forEach(function (img) {
      img.addEventListener('error', function () {
        img.classList.add('placeholder');
        img.removeAttribute('src');
      }, { once: true });
    });

    if (window.civicMap && geo) {
      overlayOnMap(geo, districts);
    }
  }

  // ---- map overlay ---------------------------------------------------------
  function overlayOnMap(geo, districts) {
    var map = window.civicMap;
    if (!map) return;

    // Drop or move the address marker.
    if (marker) marker.setLngLat([geo.lng, geo.lat]);
    else marker = new maplibregl.Marker({ color: MATCHED_STROKE })
                                .setLngLat([geo.lng, geo.lat]).addTo(map);

    // One feature per layer that had a hit, using the geometry the API
    // returned inline. layer_id rides as a property so we can style per
    // layer later (e.g. only show the assembly outline if you mouse over
    // that row in the panel).
    var subset = {
      type: 'FeatureCollection',
      features: districts
        .filter(function (d) { return d.geometry; })
        .map(function (d) {
          return { type: 'Feature', geometry: d.geometry,
                   properties: { layer_id: d.layer_id, district: d.district } };
        })
    };

    var addOrUpdate = function () {
      if (map.getSource('your-districts')) {
        map.getSource('your-districts').setData(subset);
      } else {
        map.addSource('your-districts', { type: 'geojson', data: subset });
        // Insert beneath the land-use pins so they remain clickable on top.
        var beforeId = map.getLayer('items') ? 'items' : undefined;
        map.addLayer({
          id: 'your-districts-fill', type: 'fill', source: 'your-districts',
          paint: { 'fill-color': LAYER_FILL, 'fill-opacity': 0.05 }
        }, beforeId);
        map.addLayer({
          id: 'your-districts-line', type: 'line', source: 'your-districts',
          paint: { 'line-color': LAYER_STROKE, 'line-width': 1.5, 'line-opacity': 0.85 }
        });
      }
    };
    if (map.isStyleLoaded()) addOrUpdate();
    else map.once('load', addOrUpdate);

    // Frame the address + matched polygons.
    try {
      var b = new maplibregl.LngLatBounds([geo.lng, geo.lat], [geo.lng, geo.lat]);
      subset.features.forEach(function (f) {
        function walk(coords) {
          if (typeof coords[0] === 'number') { b.extend(coords); return; }
          coords.forEach(walk);
        }
        if (f.geometry && f.geometry.coordinates) walk(f.geometry.coordinates);
      });
      map.fitBounds(b, { padding: 64, maxZoom: 13, duration: 600 });
    } catch (e) { /* no-op */ }
  }

  // ---- form submit ---------------------------------------------------------
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = (input.value || '').trim();
    if (!q) return;

    submitBtn.disabled = true;
    setStatus('Looking up your address…', 'busy');

    fetch('/api/districts?address=' + encodeURIComponent(q))
      .then(function (r) {
        if (r.status === 404) throw new Error("We couldn't place that address. Try adding city + state, or use a nearby intersection.");
        if (!r.ok) throw new Error('Lookup failed (HTTP ' + r.status + ').');
        return r.json();
      })
      .then(function (payload) {
        setStatus('');
        render(payload);
      })
      .catch(function (err) {
        resultsEl.hidden = true;
        setStatus(err.message || 'Lookup failed.', 'error');
      })
      .finally(function () {
        submitBtn.disabled = false;
      });
  });
})();
