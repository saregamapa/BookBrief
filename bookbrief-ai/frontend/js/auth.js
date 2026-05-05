/**
 * BookBrief AI — JWT session helpers.
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

  function isLoggedIn() {
    return !!getToken();
  }

  global.BBAuth = {
    getToken: getToken,
    getUser: getUser,
    setSession: setSession,
    clearSession: clearSession,
    login: login,
    register: register,
    logout: logout,
    forgotPassword: forgotPassword,
    resetPassword: resetPassword,
    isLoggedIn: isLoggedIn,
  };
})(typeof window !== "undefined" ? window : this);
