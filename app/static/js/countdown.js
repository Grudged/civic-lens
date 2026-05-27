/* Live countdown — upgrades server-rendered <span class="countdown" data-when="ISO"> elements to
   a ticking "in 5d 14h". Progressive enhancement: if JS is off, the server's static text stands.
   data-when is a naive local (Pacific) datetime; the audience is local, so new Date() is correct. */
(function () {
  function phrase(ms) {
    if (ms <= 0) return "happening today";
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400); s -= d * 86400;
    var h = Math.floor(s / 3600); s -= h * 3600;
    var m = Math.floor(s / 60);
    if (d > 0) return "in " + d + "d " + h + "h";
    if (h > 0) return "in " + h + "h " + m + "m";
    return "in " + m + "m";
  }
  function tick() {
    var now = Date.now();
    document.querySelectorAll(".countdown[data-when]").forEach(function (el) {
      var t = new Date(el.getAttribute("data-when")).getTime();
      if (isNaN(t)) return;
      var left = t - now;
      el.textContent = phrase(left);
      el.classList.toggle("soon", left > 0 && left < 2 * 86400000); // < 2 days = urgent color
    });
  }
  tick();
  setInterval(tick, 30000);
})();
