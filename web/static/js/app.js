/* FinSight — the whole of the client-side code.
 *
 * Everything here is progressive enhancement. Every row is a real <a> with a
 * real href, so with JavaScript disabled the app still works — it just does a
 * full page load per selection instead of swapping one pane. Nothing below
 * creates behaviour that does not already exist without it.
 *
 * The performance story, in order of how much it matters:
 *
 *   1. Selecting a finding fetches ~6KB of HTML, not a whole page.
 *   2. It is prefetched on hover/focus, so by the time you click it is usually
 *      already in memory and the swap is synchronous.
 *   3. Responses are cached for the session, so revisiting is always free.
 *   4. Filtering is client-side against a haystack the server prebuilt, so it
 *      never touches the network and never reads layout.
 */

(function () {
  "use strict";

  var listpane = document.getElementById("listpane");
  var detailpane = document.getElementById("detailpane");
  if (!detailpane) return;

  /* ──────────────────────────────────────────────────────────────────────
     Detail fetching
     ────────────────────────────────────────────────────────────────────── */

  /* url -> Promise<string>. A Promise rather than the text itself, so two
   * events racing for the same row (hover then a fast click) share one
   * request instead of firing two. */
  var cache = new Map();
  var inflight = null;          // AbortController for the visible request
  var currentUrl = location.pathname + location.search;

  function detailUrl(row) {
    /* The row's href is the full-page URL; the fragment lives at /finding/<id>
     * with the same query so the run and mode carry over. */
    var params = new URLSearchParams(location.search);
    params.delete("sel");
    var qs = params.toString();
    return "/finding/" + encodeURIComponent(row.dataset.id) + (qs ? "?" + qs : "");
  }

  function load(url) {
    var hit = cache.get(url);
    if (hit) return hit;
    var promise = fetch(url, { headers: { "X-Fragment": "1" } })
      .then(function (res) { return res.text(); })
      .catch(function () {
        /* A failed prefetch must not poison the cache — the click that follows
         * should get a fresh attempt rather than an error forever. */
        cache.delete(url);
        return null;
      });
    cache.set(url, promise);
    return promise;
  }

  /* Prefetch on hover and on focus. Both are free signals of intent, and the
   * request is small enough that a few wasted ones cost nothing. */
  function prefetch(row) {
    if (!row || !row.dataset.id) return;
    load(detailUrl(row));
  }

  function markSelected(row) {
    var previous = listpane && listpane.querySelector(".frow.is-selected");
    if (previous === row) return;
    if (previous) {
      previous.classList.remove("is-selected");
      previous.setAttribute("aria-selected", "false");
    }
    row.classList.add("is-selected");
    row.setAttribute("aria-selected", "true");
  }

  function select(row, push) {
    if (!row || !row.dataset.id) return;

    /* Paint the selection before the response lands. The click is
     * acknowledged in the same frame; the content follows. */
    markSelected(row);

    var url = detailUrl(row);
    var pageUrl = row.getAttribute("href");

    if (push !== false && pageUrl !== currentUrl) {
      history.pushState({ id: row.dataset.id }, "", pageUrl);
      currentUrl = pageUrl;
    }

    if (inflight) inflight.abort();

    var cached = cache.get(url);
    var settled = false;

    /* Only show the busy state if the response is actually slow. Flashing it
     * for a 20ms cache hit is worse than not showing it at all. */
    var timer = setTimeout(function () {
      if (!settled) detailpane.setAttribute("aria-busy", "true");
    }, 120);

    load(url).then(function (html) {
      settled = true;
      clearTimeout(timer);
      detailpane.setAttribute("aria-busy", "false");
      if (html === null) {
        /* The fetch failed. Fall back to a real navigation rather than
         * leaving a stale pane that no longer matches the highlighted row. */
        window.location.href = pageUrl;
        return;
      }
      detailpane.innerHTML = html;
      detailpane.scrollTop = 0;
    });

    void cached;
  }

  /* ──────────────────────────────────────────────────────────────────────
     Events
     ────────────────────────────────────────────────────────────────────── */

  if (listpane) {
    listpane.addEventListener("mouseover", function (e) {
      var row = e.target.closest(".frow");
      if (row) prefetch(row);
    });
    listpane.addEventListener("focusin", function (e) {
      var row = e.target.closest(".frow");
      if (row) prefetch(row);
    });

    listpane.addEventListener("click", function (e) {
      var row = e.target.closest(".frow");
      if (!row) return;
      /* Leave the browser's own behaviour alone for modified clicks — a
       * ctrl/cmd/middle click must still open a new tab. */
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      e.preventDefault();
      select(row, true);
    });
  }

  window.addEventListener("popstate", function () {
    /* Back/forward. Re-select from the URL without pushing a new entry. */
    currentUrl = location.pathname + location.search;
    var id = new URLSearchParams(location.search).get("sel");
    var row = id && document.getElementById("frow-" + CSS.escape(id));
    if (row) select(row, false);
    else window.location.reload();
  });

  /* ──────────────────────────────────────────────────────────────────────
     Filter — client-side, against the server-built haystack
     ────────────────────────────────────────────────────────────────────── */

  var filter = document.getElementById("finding-filter");
  var emptyMsg = document.getElementById("list-empty");
  var countEl = document.getElementById("list-count");
  var rows = listpane ? Array.prototype.slice.call(listpane.querySelectorAll(".frow")) : [];
  var groups = listpane ? Array.prototype.slice.call(listpane.querySelectorAll(".group")) : [];

  /* Read every haystack once, up front. Doing it per keystroke would touch the
   * DOM O(rows) times on every character; this way the loop is pure string
   * comparison over an array already in memory. */
  var index = rows.map(function (row) {
    return { el: row, text: row.dataset.haystack || "" };
  });

  function applyFilter(term) {
    var q = term.trim().toLowerCase();
    var shown = 0;

    for (var i = 0; i < index.length; i++) {
      var match = !q || index[i].text.indexOf(q) !== -1;
      index[i].el.classList.toggle("is-hidden", !match);
      if (match) shown++;
    }

    /* Hide a group whose every row went away, so its sticky header does not
     * hang over an empty stretch. */
    for (var g = 0; g < groups.length; g++) {
      var visible = groups[g].querySelector(".frow:not(.is-hidden)");
      groups[g].classList.toggle("is-hidden", !visible);
    }

    if (emptyMsg) emptyMsg.hidden = shown !== 0;
    if (countEl) countEl.textContent = String(shown);
  }

  if (filter) {
    var pending = null;
    filter.addEventListener("input", function () {
      /* Coalesce to one pass per frame. Holding a key down fires input far
       * faster than the screen refreshes; without this the extra passes are
       * pure waste. */
      if (pending) cancelAnimationFrame(pending);
      pending = requestAnimationFrame(function () {
        pending = null;
        applyFilter(filter.value);
      });
    });
    /* Escape clears rather than blurs — clearing is what you actually want,
     * and the field keeps focus so you can type again immediately. */
    filter.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && filter.value) {
        e.preventDefault();
        filter.value = "";
        applyFilter("");
      }
    });
  }

  /* ──────────────────────────────────────────────────────────────────────
     Keyboard
     ────────────────────────────────────────────────────────────────────── */

  function visibleRows() {
    return rows.filter(function (r) { return !r.classList.contains("is-hidden"); });
  }

  function move(delta) {
    var list = visibleRows();
    if (!list.length) return;
    var current = listpane.querySelector(".frow.is-selected");
    var i = list.indexOf(current);
    var next = list[Math.max(0, Math.min(list.length - 1, i + delta))];
    if (!next || next === current) return;
    next.focus({ preventScroll: true });
    next.scrollIntoView({ block: "nearest" });
    select(next, true);
  }

  document.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);

    /* "/" focuses the filter, the convention everywhere from Gmail to GitHub. */
    if (e.key === "/" && !typing && filter) {
      e.preventDefault();
      filter.focus();
      filter.select();
      return;
    }
    if (typing) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); move(-1); }
  });

  /* Deep link: bring the selected row into view on first paint. */
  var selected = listpane && listpane.querySelector(".frow.is-selected");
  if (selected) selected.scrollIntoView({ block: "nearest" });
})();
