/**
 * libraire — JWT session helpers.
 */
(function (global) {
  "use strict";

  var TOKEN_KEY = "bookbrief_token";
  var USER_KEY = "bookbrief_user";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function getUser() {
    try {
      var raw = localStorage.getItem(USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function setSession(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  /**
   * Decode JWT payload without verifying the signature.
   * Used only for client-side expiry checks; server always re-validates.
   */
  function _decodeJwtPayload(token) {
    try {
      var parts = token.split(".");
      if (parts.length !== 3) return null;
      var b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
      var json = decodeURIComponent(
        atob(b64)
          .split("")
          .map(function (c) {
            return "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2);
          })
          .join("")
      );
      return JSON.parse(json);
    } catch (_) {
      return null;
    }
  }

  /**
   * Returns true if the stored token is present and not yet expired (client-side only).
   * The server performs authoritative validation on every request.
   */
  function isLoggedIn() {
    var token = getToken();
    if (!token) return false;
    var payload = _decodeJwtPayload(token);
    if (!payload || !payload.exp) return true; // no exp claim — let the server decide
    return Math.floor(Date.now() / 1000) < payload.exp;
  }

  async function login(email, password) {
    var data = await global.BBApi.apiFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: email, password: password }),
    });
    setSession(data.access_token, data.user);
    return data;
  }

  async function register(email, password, fullName) {
    var body = { email: email, password: password };
    if (fullName && String(fullName).trim()) {
      body.full_name = String(fullName).trim();
    }
    var data = await global.BBApi.apiFetch("/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });
    setSession(data.access_token, data.user);
    return data;
  }

  async function logout() {
    if (getToken()) {
      try {
        await global.BBApi.apiFetch("/auth/logout", { method: "POST" });
      } catch (_) {
        /* still clear local session */
      }
    }
    clearSession();
  }

  /**
   * Change password while authenticated.
   * On success, stores the new token (all other sessions are revoked).
   */
  async function changePassword(currentPassword, newPassword) {
    var data = await global.BBApi.apiFetch("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    setSession(data.access_token, data.user);
    return data;
  }

  /**
   * Revoke all active sessions (including other devices).
   * The current local session is cleared after the server call.
   */
  async function revokeAllSessions() {
    await global.BBApi.apiFetch("/auth/revoke-all", { method: "POST" });
    clearSession();
  }

  async function forgotPassword(email) {
    return global.BBApi.apiFetch("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email: email }),
    });
  }

  async function resetPassword(token, newPassword) {
    return global.BBApi.apiFetch("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token: token, new_password: newPassword }),
    });
  }

  global.BBAuth = {
    getToken: getToken,
    getUser: getUser,
    setSession: setSession,
    clearSession: clearSession,
    login: login,
    register: register,
    logout: logout,
    changePassword: changePassword,
    revokeAllSessions: revokeAllSessions,
    forgotPassword: forgotPassword,
    resetPassword: resetPassword,
    isLoggedIn: isLoggedIn,
  };
})(typeof window !== "undefined" ? window : this);
