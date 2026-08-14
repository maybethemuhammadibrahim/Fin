/* FinSight — the whole of the client-side code.
 *
 * There is deliberately almost none. Every screen is rendered on the server
 * and every navigation is a real URL, so a finding can be linked to, the back
 * button works, and the page is identical with JavaScript switched off. The
 * two things below are the exceptions, and both are progressive: without them
 * the page still renders, it just needs one more click.
 */

(function () {
  "use strict";

  /* A findings row is a six-column CSS grid. Wrapping it in an <a> would
   * collapse that layout — an anchor is not a grid container in the way the
   * columns need — so the row carries data-href and picks up the click here.
   * role="link" and tabindex are set in the template, so it is still reachable
   * by keyboard; this adds Enter and Space to match a real link. */
  function follow(el) {
    var href = el.getAttribute("data-href");
    if (href) window.location.href = href;
  }

  document.addEventListener("click", function (event) {
    var row = event.target.closest("[data-href]");
    if (!row) return;
    // Let a real control inside the row do its own job.
    if (event.target.closest("a, button, select, input")) return;
    follow(row);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var row = event.target.closest && event.target.closest("[data-href]");
    if (!row) return;
    event.preventDefault();
    follow(row);
  });

  /* Keep the selected finding in view when the page loads from a deep link.
   * Without this, opening /?sel=42 lands you at the top of a long table with
   * the highlighted row somewhere below the fold. */
  var selected = document.querySelector(".frow.is-selected");
  if (selected && window.location.search.indexOf("sel=") !== -1) {
    var top = selected.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight) {
      selected.scrollIntoView({ block: "center" });
    }
  }
})();
