/**
 * BookBrief AI — fetch wrapper (same-origin API).
 */
(function (global) {
  "use strict";

  var API_BASE = "";

  function buildHeaders(options, isFormData) {
    var h = Object.assign({}, (options && options.headers) || {});
    var token = global.BBAuth && typeof global.BBAuth.getToken === "function" ? global.BBAuth.getToken() : null;
    if (token) {
      h.Authorization = "Bearer " + token;
    }
    if (isFormData) {
      delete h["Content-Type"];
      return h;
    }
    if (!h["Content-Type"] && options && options.body && typeof options.body === "string") {
      h["Content-Type"] = "application/json";
    }
    return h;
  }

  function parseBody(text) {
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch (_) {
      return { detail: text };
    }
  }

  function formatDetail(detail) {
    if (detail == null) return "";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map(function (x) {
          if (typeof x === "string") return x;
          if (x && x.msg) return x.msg;
          return JSON.stringify(x);
        })
        .join(", ");
    }
    return JSON.stringify(detail);
  }

  /**
   * @param {string} path
   * @param {RequestInit} [options]
   */
  async function apiFetch(path, options) {
    options = options || {};
    var isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
    var url = API_BASE + path;
    var headers = buildHeaders(options, isForm);
    var res = await fetch(url, Object.assign({}, options, { headers: headers }));
    var text = await res.text();
    var data = parseBody(text);
    if (!res.ok) {
      var msg =
        (data && (data.detail || data.message)) ||
        (typeof data === "string" ? data : null) ||
        res.statusText ||
        "Request failed";
      msg = formatDetail(msg) || String(msg);
      var err = new Error(msg);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function buildQuery(params) {
    if (!params) return "";
    var parts = [];
    Object.keys(params).forEach(function (k) {
      var v = params[k];
      if (v === undefined || v === null || v === "") return;
      parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(String(v)));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  var summaries = {
    list: function (params) {
      return apiFetch("/summaries" + buildQuery(params || {}));
    },
    get: function (id) {
      return apiFetch("/summaries/" + encodeURIComponent(String(id)));
    },
    remove: function (id) {
      return apiFetch("/summaries/" + encodeURIComponent(String(id)), { method: "DELETE" });
    },
    createJson: function (body) {
      return apiFetch("/summaries", { method: "POST", body: JSON.stringify(body) });
    },
    /** @param {FormData} formData */
    createPdf: function (formData) {
      return apiFetch("/summaries/pdf", { method: "POST", body: formData });
    },
  };

  global.BBApi = {
    apiFetch: apiFetch,
    setApiBase: function (b) {
      API_BASE = b || "";
    },
    summaries: summaries,
  };
})(typeof window !== "undefined" ? window : this);
