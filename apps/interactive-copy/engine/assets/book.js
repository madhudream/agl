/* Shell: theme, contents drawer, reading progress, chapters read, copy buttons, light code colouring. */
(function () {
  "use strict";
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private window */ } }
  };
  var root = document.documentElement, body = document.body, DONE = "mb-done:" + (body.dataset.book || "site");

  // theme
  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("mb-theme", root.dataset.theme); } catch (e) { /* ignore */ }
    document.dispatchEvent(new CustomEvent("mb:theme"));
  });

  // contents drawer
  var navBtn = document.getElementById("nav-toggle");
  function closeNav() { body.classList.remove("nav-open"); if (navBtn) navBtn.setAttribute("aria-expanded", "false"); }
  if (navBtn) navBtn.addEventListener("click", function () {
    var open = body.classList.toggle("nav-open");
    navBtn.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("click", function (e) {
    if (body.classList.contains("nav-open") && !e.target.closest("#sidebar") && !e.target.closest("#nav-toggle")) closeNav();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeNav(); });
  var cur = document.querySelector('.sidebar a[aria-current="page"]');
  if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "center" });

  // reading progress
  var bar = document.querySelector(".progress i");
  function onScroll() {
    var h = document.documentElement.scrollHeight - innerHeight;
    if (bar) bar.style.width = (h > 0 ? Math.min(100, (scrollY / h) * 100) : 0) + "%";
  }
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // chapters read
  var done = store.get(DONE, {});
  function paintDone() {
    var links = document.querySelectorAll("[data-slug]"), total = document.querySelectorAll(".sidebar a[data-slug]").length, n = 0;
    links.forEach(function (a) { a.classList.toggle("is-done", !!done[a.dataset.slug]); });
    document.querySelectorAll(".sidebar a[data-slug]").forEach(function (a) { if (done[a.dataset.slug]) n++; });
    var c = document.getElementById("done-count"), b = document.getElementById("done-bar");
    if (c) c.textContent = n;
    if (b && total) b.style.width = (n / total) * 100 + "%";
    var btn = document.getElementById("mark-done");
    if (btn) {
      var d = !!done[btn.dataset.slug];
      btn.classList.toggle("is-done", d);
      btn.textContent = d ? "✓ Read. Click to undo" : "Mark this chapter as read";
    }
    var start = document.getElementById("start-btn");
    if (start && n > 0) {
      var next = Array.prototype.find.call(document.querySelectorAll(".sidebar a[data-slug]"), function (a) { return !done[a.dataset.slug]; });
      if (next) { start.href = next.getAttribute("href"); start.textContent = "Continue with chapter " + next.querySelector(".nav-n").textContent; }
    }
  }
  var mark = document.getElementById("mark-done");
  if (mark) mark.addEventListener("click", function () {
    if (done[mark.dataset.slug]) delete done[mark.dataset.slug]; else done[mark.dataset.slug] = Date.now();
    store.set(DONE, done);
    paintDone();
  });
  paintDone();

  // code: copy button and a light colouring pass
  var KW = /\b(from|import|def|return|for|in|if|else|elif|not|and|or|class|with|as|print|None|True|False|lambda|while|try|except|SELECT|FROM|WHERE|AND|ORDER BY|LIMIT|INSERT|UPDATE|DELETE)\b/g;
  function colour(src) {
    // src is already HTML-escaped text. Order: comments, strings, numbers, keywords, using placeholders.
    var keep = [];
    // placeholders carry their index as one private-use character, not digits, or the number pass below would eat them
    function hold(cls) { return function (m) { keep.push('<span class="' + cls + '">' + m + "</span>"); return "\u0001" + String.fromCharCode(0xE000 + keep.length - 1) + "\u0002"; }; }
    src = src.replace(/(^|\s)(#[^\n]*)/g, function (m, a, b) { return a + hold("tok-c")(b); });
    src = src.replace(/("""[\s\S]*?"""|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')/g, hold("tok-s"));
    src = src.replace(/\b\d[\d_,.]*\b/g, hold("tok-n"));
    src = src.replace(KW, hold("tok-k"));
    return src.replace(/\u0001([\uE000-\uF8FF])\u0002/g, function (m, c) { return keep[c.charCodeAt(0) - 0xE000]; });
  }
  document.querySelectorAll(".prose pre").forEach(function (pre) {
    var code = pre.querySelector("code");
    if (code && /language-(python|sql|bash)/.test(code.className) && !code.querySelector("span")) {
      try { code.innerHTML = colour(code.innerHTML); } catch (e) { /* leave plain */ }
    }
    if (!code) return;
    var b = document.createElement("button");
    b.className = "copy-btn"; b.type = "button"; b.textContent = "Copy";
    b.addEventListener("click", function () {
      var text = code.textContent;
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () {
        b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1400);
      }, function () { b.textContent = "Select and copy"; });
    });
    pre.appendChild(b);
  });

  window.MBStore = store;
})();
