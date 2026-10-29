// Version resolution for the versioned Constitution Annotated demo.
//
// ?date=<datetime> on any page goes to the latest archived version of that page
// at or before <datetime>; the query stays in the address so the page shows both
// the version and the queried datetime. Unversioned addresses without ?date= go
// to the latest version of the page. Mirrors cav/versions.py.
(function () {
  "use strict";
  var VERSION_RE = /^\d{8}T\d{6}Z$/;
  var QUERY_RE = /^(\d{4})(?:-?(\d{2})(?:-?(\d{2})(?:[T ](\d{2})(?::?(\d{2})(?::?(\d{2})(?:\.\d+)?)?)?)?)?)?(Z|[+-]\d{2}:?\d{2})?$/;

  function meta(name) {
    var el = document.querySelector('meta[name="' + name + '"]');
    return el ? el.getAttribute("content") : null;
  }

  // Latest UTC instant denoted by a query, as a version-id string.
  function parseQuery(q) {
    var m = QUERY_RE.exec(q.trim());
    if (!m) return null;
    var y = +m[1], mo = m[2] ? +m[2] - 1 : null, d = m[3] ? +m[3] : null;
    var h = m[4] ? +m[4] : null, mi = m[5] ? +m[5] : null, s = m[6] ? +m[6] : null;
    var start, end;
    if (mo === null) { start = Date.UTC(y, 0, 1); end = Date.UTC(y + 1, 0, 1); }
    else if (d === null) { start = Date.UTC(y, mo, 1); end = Date.UTC(y, mo + 1, 1); }
    else if (h === null) { start = Date.UTC(y, mo, d); end = start + 864e5; }
    else if (mi === null) { start = Date.UTC(y, mo, d, h); end = start + 36e5; }
    else if (s === null) { start = Date.UTC(y, mo, d, h, mi); end = start + 6e4; }
    else { start = Date.UTC(y, mo, d, h, mi, s); end = start + 1e3; }
    var off = 0;
    if (m[7] && m[7] !== "Z") {
      var t = m[7].replace(":", "");
      off = (t[0] === "+" ? 1 : -1) * (+t.slice(1, 3) * 60 + +t.slice(3, 5)) * 6e4;
    }
    if (isNaN(end)) return null;
    return toId(new Date(end - 1e3 - off));
  }

  function toId(dt) {
    return dt.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  }

  function display(v) {
    return v.slice(0, 4) + "-" + v.slice(4, 6) + "-" + v.slice(6, 8) + " " +
      v.slice(9, 11) + ":" + v.slice(11, 13) + ":" + v.slice(13, 15) + " UTC";
  }

  // Inverse of cav/paths.py versioned(): [source path, version or null].
  function unversioned(path) {
    var segs = path.replace(/^\//, "").split("/");
    if (VERSION_RE.test(segs[0])) return ["/" + segs.slice(1).join("/"), segs[0]];
    if (segs.length > 1 && VERSION_RE.test(segs[1]))
      return ["/" + [segs[0]].concat(segs.slice(2)).join("/"), segs[1]];
    return [path, null];
  }

  function versioned(path, v) {
    var rest = path.replace(/^\//, "");
    var i = rest.indexOf("/");
    return i >= 0 ? "/" + rest.slice(0, i) + "/" + v + rest.slice(i) : "/" + v + "/" + rest;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function exists(url) {
    return fetch(url, { method: "HEAD" }).then(function (r) { return r.ok; }, function () { return false; });
  }

  // First candidate version (newest first) whose copy of path exists.
  function firstExisting(base, path, candidates) {
    var i = 0;
    function next() {
      if (i >= candidates.length) return Promise.resolve(null);
      var v = candidates[i++];
      return exists(base + versioned(path, v)).then(function (ok) { return ok ? v : next(); });
    }
    return next();
  }

  function note(html) {
    var el = document.getElementById("cav-query");
    if (!el) return;
    el.innerHTML = html;
    el.hidden = false;
  }

  var base = meta("cav-base") || "";
  var current = meta("cav-version") || null;
  var path = meta("cav-path");
  if (!path) {
    var p = location.pathname;
    if (base && p.indexOf(base) === 0) p = p.slice(base.length);
    var u = unversioned(p);
    path = u[0];
    current = u[1];
  }
  var params = new URLSearchParams(location.search);
  var q = params.get("date");

  fetch(base + "/_cav/versions.json").then(function (r) { return r.json(); }).then(function (data) {
    var versions = data.versions.slice().sort();
    var latest = versions[versions.length - 1];
    var candidates, target;

    if (q) {
      target = parseQuery(q);
      if (!target) {
        note("Queried <code>" + escapeHtml(q) + "</code>: not a recognized date. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ.");
        return;
      }
      candidates = versions.filter(function (v) { return v <= target; }).reverse();
      if (!candidates.length) {
        note("Queried " + escapeHtml(q) + ": no archived version exists that early. Earliest is " +
          '<a href="' + base + versioned(path, versions[0]) + '">' + display(versions[0]) + "</a>.");
        return;
      }
      if (candidates[0] === current) {
        note("Queried " + escapeHtml(q) + " (" + display(target) + ")");
        return;
      }
    } else if (current) {
      if (current !== latest) {
        note('<a href="' + base + path + '">Newer version available</a>');
      }
      return;
    } else {
      candidates = versions.slice().reverse();
    }

    firstExisting(base, path, candidates).then(function (v) {
      if (v && v === current) { note("Queried " + escapeHtml(q) + " (" + display(target) + ")"); return; }
      if (!v) {
        note("This page has no archived version" + (q ? " as of " + escapeHtml(q) : "") + ".");
        return;
      }
      var dest = base + versioned(path, v) + (q ? "?date=" + encodeURIComponent(q) : "") + location.hash;
      location.replace(dest);
    });
  });
})();
