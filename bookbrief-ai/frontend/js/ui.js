/**
 * BookBrief AI — theme toggle, toast notifications, skeleton loaders, and UI helpers.
 */
(function (global) {
  "use strict";

  var STORAGE_KEY = "bookbrief-theme";

  // ── Theme ─────────────────────────────────────────────────────────────────

  function getStoredTheme() {
    return localStorage.getItem(STORAGE_KEY);
  }

  function prefersDark() {
    return global.matchMedia && global.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function applyTheme(mode) {
    var root = document.documentElement;
    if (mode === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }

  function initThemeToggle(buttonSelector) {
    var btn = buttonSelector ? document.querySelector(buttonSelector) : null;
    if (!btn) return;

    function syncLabel() {
      var dark = document.documentElement.classList.contains("dark");
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
      btn.title = dark ? "Switch to light mode" : "Switch to dark mode";
      var span = btn.querySelector("[data-theme-label]");
      if (span) span.textContent = dark ? "Light" : "Dark";
      var icon = btn.querySelector("[data-theme-icon]");
      if (icon) icon.textContent = dark ? "☀" : "◐";
    }

    btn.addEventListener("click", function () {
      var next = document.documentElement.classList.contains("dark") ? "light" : "dark";
      localStorage.setItem(STORAGE_KEY, next);
      applyTheme(next);
      syncLabel();
    });

    syncLabel();
  }

  function wireMobileNav(toggleSelector, panelSelector) {
    var toggle = document.querySelector(toggleSelector);
    var panel = document.querySelector(panelSelector);
    if (!toggle || !panel) return;
    toggle.addEventListener("click", function () {
      var open = panel.classList.toggle("hidden") === false;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // ── Alert banner ─────────────────────────────────────────────────────────

  function showAlert(el, message, kind) {
    if (!el) return;
    el.textContent = message || "";
    el.className = el.className.replace(/\b(hidden|text-red-\d+|text-emerald-\d+|dark:[^\s]+)\b/g, "").trim();
    if (!message) {
      el.classList.add("hidden");
      return;
    }
    if (kind === "success") {
      el.classList.add("text-emerald-700", "dark:text-emerald-400");
    } else {
      el.classList.add("text-red-600", "dark:text-red-400");
    }
  }

  // ── Toast notifications ───────────────────────────────────────────────────
  // showToast(message, kind, durationMs)
  //   kind: "success" | "error" | "info"  (default "info")
  //   Auto-dismisses after durationMs (default 3500).

  var _toastContainer = null;

  function _ensureToastContainer() {
    if (_toastContainer) return _toastContainer;
    _toastContainer = document.createElement("div");
    _toastContainer.setAttribute("aria-live", "polite");
    _toastContainer.setAttribute("aria-atomic", "false");
    _toastContainer.style.cssText =
      "position:fixed;bottom:1.25rem;right:1.25rem;z-index:9999;display:flex;flex-direction:column;gap:.5rem;pointer-events:none;max-width:20rem;";
    document.body.appendChild(_toastContainer);
    return _toastContainer;
  }

  function showToast(message, kind, durationMs) {
    var container = _ensureToastContainer();
    durationMs = durationMs || 3500;
    kind = kind || "info";

    var colorMap = {
      success: "background:#166534;color:#dcfce7;",
      error: "background:#991b1b;color:#fee2e2;",
      info: "background:#1c1917;color:#f5f5f4;",
    };
    var iconMap = { success: "✓", error: "✕", info: "ℹ" };

    var toast = document.createElement("div");
    toast.style.cssText =
      "pointer-events:auto;display:flex;align-items:center;gap:.625rem;padding:.625rem .875rem;" +
      "border-radius:.75rem;font-size:.8125rem;font-weight:500;line-height:1.4;box-shadow:0 4px 20px rgba(0,0,0,.35);" +
      "opacity:0;transform:translateY(.5rem);transition:opacity .2s ease,transform .2s ease;" +
      (colorMap[kind] || colorMap.info);

    var icon = document.createElement("span");
    icon.style.cssText = "flex-shrink:0;font-size:.875rem;";
    icon.textContent = iconMap[kind] || iconMap.info;

    var text = document.createElement("span");
    text.textContent = message;

    toast.appendChild(icon);
    toast.appendChild(text);
    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        toast.style.opacity = "1";
        toast.style.transform = "translateY(0)";
      });
    });

    // Auto-dismiss
    setTimeout(function () {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(.5rem)";
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 220);
    }, durationMs);
  }

  // ── Button loading state ──────────────────────────────────────────────────
  // Returns a restore function: var restore = setLoadingBtn(btn, "Generating…");
  //                             restore(); // undo

  function setLoadingBtn(btn, loadingText) {
    var orig = btn.textContent;
    var origDisabled = btn.disabled;
    btn.disabled = true;
    btn.textContent = loadingText || "Loading…";
    return function () {
      btn.disabled = origDisabled;
      btn.textContent = orig;
    };
  }

  // ── Skeleton / shimmer helpers ────────────────────────────────────────────

  var _shimmerStyle = (function () {
    var id = "bb-shimmer";
    if (!document.getElementById(id)) {
      var s = document.createElement("style");
      s.id = id;
      s.textContent =
        "@keyframes bb-shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}" +
        ".bb-skeleton{border-radius:.5rem;background:linear-gradient(90deg,#e7e5e4 25%,#d6d3d1 50%,#e7e5e4 75%);" +
        "background-size:400% 100%;animation:bb-shimmer 1.4s ease-in-out infinite;}" +
        ".dark .bb-skeleton{background:linear-gradient(90deg,#292524 25%,#44403c 50%,#292524 75%);background-size:400% 100%;}";
      document.head.appendChild(s);
    }
  })();

  /**
   * Replace the children of `container` with N skeleton rows.
   * Each row is an object: { h: height (px), w: width (%), mt: marginTop (px) }
   */
  function showSkeleton(container, rows) {
    var frag = document.createDocumentFragment();
    (rows || [{ h: 16, w: 60, mt: 0 }, { h: 14, w: 90, mt: 8 }, { h: 14, w: 75, mt: 8 }]).forEach(function (r) {
      var el = document.createElement("div");
      el.className = "bb-skeleton";
      el.style.cssText =
        "height:" + (r.h || 16) + "px;width:" + (r.w || 80) + "%;margin-top:" + (r.mt || 0) + "px;";
      el.setAttribute("aria-hidden", "true");
      frag.appendChild(el);
    });
    container.innerHTML = "";
    container.appendChild(frag);
  }

  // ── Progress step tracker ─────────────────────────────────────────────────
  // Used by summarize.html for the polling progress UI.
  //
  // steps = [{id, label}]
  // Returns an object with .setStatus(id, 'pending'|'active'|'done'|'error')

  function createProgressSteps(container, steps) {
    container.innerHTML = "";
    var stepEls = {};

    steps.forEach(function (s, i) {
      var row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:.625rem;padding:.375rem 0;";

      var dot = document.createElement("span");
      dot.style.cssText =
        "flex-shrink:0;width:1.25rem;height:1.25rem;border-radius:50%;display:flex;" +
        "align-items:center;justify-content:center;font-size:.65rem;font-weight:700;transition:all .3s;";
      dot.setAttribute("aria-hidden", "true");

      var label = document.createElement("span");
      label.textContent = s.label;
      label.style.cssText = "font-size:.8125rem;transition:color .3s;";

      row.appendChild(dot);
      row.appendChild(label);
      container.appendChild(row);
      stepEls[s.id] = { dot: dot, label: label };
    });

    function setStatus(id, state) {
      var el = stepEls[id];
      if (!el) return;
      var dark = document.documentElement.classList.contains("dark");
      var styles = {
        pending: {
          dot: "background:" + (dark ? "#44403c" : "#e7e5e4") + ";color:" + (dark ? "#78716c" : "#a8a29e") + ";",
          label: "color:" + (dark ? "#57534e" : "#a8a29e") + ";",
          icon: "·",
        },
        active: {
          dot: "background:#b45309;color:#fff;animation:bb-shimmer 1s ease-in-out infinite;background-size:200% 100%;",
          label: "color:" + (dark ? "#fbbf24" : "#92400e") + ";font-weight:600;",
          icon: "…",
        },
        done: {
          dot: "background:#166534;color:#fff;",
          label: "color:" + (dark ? "#4ade80" : "#166534") + ";",
          icon: "✓",
        },
        error: {
          dot: "background:#991b1b;color:#fff;",
          label: "color:" + (dark ? "#f87171" : "#991b1b") + ";",
          icon: "✕",
        },
      };
      var st = styles[state] || styles.pending;
      el.dot.style.cssText =
        "flex-shrink:0;width:1.25rem;height:1.25rem;border-radius:50%;display:flex;" +
        "align-items:center;justify-content:center;font-size:.65rem;font-weight:700;transition:all .3s;" +
        st.dot;
      el.dot.textContent = st.icon;
      el.label.style.cssText = "font-size:.8125rem;transition:color .3s;" + st.label;
    }

    steps.forEach(function (s) {
      setStatus(s.id, "pending");
    });

    return { setStatus: setStatus };
  }

  // ── Status badge helper ───────────────────────────────────────────────────

  var _STATUS_COLORS = {
    completed: "background:#166534;color:#dcfce7;",
    failed: "background:#991b1b;color:#fee2e2;",
    processing: "background:#92400e;color:#fef3c7;",
    pending: "background:#1e3a5f;color:#dbeafe;",
  };

  function statusBadge(status) {
    var colors = _STATUS_COLORS[status] || "background:#292524;color:#f5f5f4;";
    return (
      '<span style="' +
      colors +
      "font-size:.6875rem;font-weight:600;padding:.1875rem .5rem;border-radius:999px;" +
      '">' +
      escapeHtml(status) +
      "</span>"
    );
  }

  // ── General helpers ───────────────────────────────────────────────────────

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function copyToClipboard(text) {
    if (global.navigator.clipboard && global.navigator.clipboard.writeText) {
      return global.navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        resolve();
      } catch (e) {
        reject(e);
      } finally {
        document.body.removeChild(ta);
      }
    });
  }

  function downloadText(filename, text, mime) {
    mime = mime || "text/markdown;charset=utf-8";
    var blob = new Blob([text], { type: mime });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  global.BBUi = {
    initThemeToggle: initThemeToggle,
    wireMobileNav: wireMobileNav,
    showAlert: showAlert,
    showToast: showToast,
    setLoadingBtn: setLoadingBtn,
    showSkeleton: showSkeleton,
    createProgressSteps: createProgressSteps,
    statusBadge: statusBadge,
    escapeHtml: escapeHtml,
    applyTheme: applyTheme,
    getStoredTheme: getStoredTheme,
    prefersDark: prefersDark,
    copyToClipboard: copyToClipboard,
    downloadText: downloadText,
  };
})(typeof window !== "undefined" ? window : this);
