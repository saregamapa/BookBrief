/**
 * BookBrief AI — fetch wrapper (same-origin API).
 */
(function (global) {
  "use strict";

  // All API calls go to the versioned prefix so the backend can introduce
  // breaking changes under /api/v2 without touching this client.
  var API_BASE = "/api/v1";

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
    getStatus: function (id) {
      return apiFetch("/summaries/" + encodeURIComponent(String(id)) + "/status");
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

    /**
     * Poll /summaries/{id}/status until the job finishes, then fetch the full detail.
     *
     * @param {number} id          - Summary ID returned by createJson / createPdf
     * @param {object} [opts]
     * @param {number} [opts.intervalMs=2000]   - Initial poll interval
     * @param {number} [opts.slowIntervalMs=5000] - Interval after 30 s
     * @param {number} [opts.timeoutMs=300000]  - Give up after 5 min
     * @param {function} [opts.onStatus]        - Called with each status string ('pending'|'processing'|...)
     * @returns {Promise<object>}               - Full SummaryDetail on completion
     */
    pollUntilDone: function (id, opts) {
      opts = opts || {};
      var intervalMs = opts.intervalMs || 2000;
      var slowIntervalMs = opts.slowIntervalMs || 5000;
      var timeoutMs = opts.timeoutMs || 300000;
      var onStatus = opts.onStatus || null;

      return new Promise(function (resolve, reject) {
        var started = Date.now();
        var timer = null;

        function poll() {
          summaries.getStatus(id).then(function (data) {
            if (onStatus) onStatus(data.status);

            if (data.status === "completed") {
              // Fetch the full detail and resolve.
              summaries.get(id).then(resolve).catch(reject);
              return;
            }
            if (data.status === "failed") {
              var err = new Error(data.error_message || "Summary generation failed");
              err.status = 422;
              reject(err);
              return;
            }

            // Still pending or processing — check timeout, then reschedule.
            var elapsed = Date.now() - started;
            if (elapsed >= timeoutMs) {
              reject(new Error("Summary timed out after " + Math.round(timeoutMs / 1000) + " s"));
              return;
            }
            var nextInterval = elapsed > 30000 ? slowIntervalMs : intervalMs;
            timer = setTimeout(poll, nextInterval);
          }).catch(function (err) {
            // Network errors during polling — retry a few times before giving up.
            var elapsed = Date.now() - started;
            if (elapsed >= timeoutMs) {
              reject(err);
            } else {
              timer = setTimeout(poll, slowIntervalMs);
            }
          });
        }

        poll();
      });
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
