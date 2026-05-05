/**
 * BookBrief AI — theme toggle, small UI helpers.
 */
(function (global) {
  "use strict";

  var STORAGE_KEY = "bookbrief-theme";

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

  /** Call on every page (after DOM exists for buttons; class applied earlier via inline script). */
  function initThemeToggle(buttonSelector) {
    var btn = buttonSelector ? document.querySelector(buttonSelector) : null;
    if (!btn) return;

    function syncLabel() {
      var dark = document.documentElement.classList.contains("dark");
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
      btn.title = dark ? "Switch to light mode" : "Switch to dark mode";
      var span = btn.querySelector("[data-theme-label]");
      if (span) {
        span.textContent = dark ? "Light" : "Dark";
      }
    }

    btn.addEventListener("click", function () {
      var next = document.documentElement.classList.contains("dark") ? "light" : "dark";
      localStorage.setItem(STORAGE_KEY, next);
      applyTheme(next === "dark" ? "dark" : "light");
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

  function showAlert(el, message, kind) {
    if (!el) return;
    el.textContent = message || "";
    el.classList.remove("hidden", "text-red-600", "text-emerald-600", "dark:text-red-400", "dark:text-emerald-400");
    if (!message) {
      el.classList.add("hidden");
      return;
    }
    el.classList.remove("hidden");
    if (kind === "success") {
      el.classList.add("text-emerald-600", "dark:text-emerald-400");
    } else {
      el.classList.add("text-red-600", "dark:text-red-400");
    }
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
    applyTheme: applyTheme,
    getStoredTheme: getStoredTheme,
    prefersDark: prefersDark,
    copyToClipboard: copyToClipboard,
    downloadText: downloadText,
  };
})(typeof window !== "undefined" ? window : this);
