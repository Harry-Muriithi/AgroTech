// ═══════════════════════════════════════════════════════════
//  AGROTECH APP CORE  —  app.js
//  Shared safety layer loaded by EVERY page (before notifications.js).
//  Provides, in one place:
//    1. escapeHtml()         – stops XSS from user-entered text
//    2. agroToast()          – simple on-screen message
//    3. fetch wrapper        – offline detect, retry, 401 auto-logout, error toast
//    4. offline banner       – tells farmers when they lose connection
//    5. global error catcher – nothing fails silently anymore
//    6. PWA registration     – installable + works on poor signal
// ═══════════════════════════════════════════════════════════

(function () {
  "use strict";

  const API_HOST = "agrotech-production-4c2f.up.railway.app";

  // ───────────────────────────────────────────────
  // 1. ESCAPE HTML  (XSS protection)
  //    Use this on ANY user text before putting it
  //    into innerHTML:  el.innerHTML = escapeHtml(name)
  // ───────────────────────────────────────────────
  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
  window.escapeHtml = window.escapeHtml || escapeHtml;

  // ───────────────────────────────────────────────
  // 2. TOAST  (self-styled, never depends on page CSS)
  // ───────────────────────────────────────────────
  let toastTimer = null;
  function agroToast(message, type) {
    type = type || "info";
    let t = document.getElementById("agro-toast");
    if (!t) {
      t = document.createElement("div");
      t.id = "agro-toast";
      t.style.cssText =
        "position:fixed;left:50%;bottom:20px;transform:translateX(-50%);" +
        "max-width:90vw;padding:12px 18px;border-radius:10px;color:#fff;" +
        "font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;font-weight:600;" +
        "box-shadow:0 6px 24px rgba(0,0,0,0.25);z-index:99999;opacity:0;" +
        "transition:opacity .2s;text-align:center;pointer-events:none";
      document.body.appendChild(t);
    }
    const colors = { info: "#1a3d2b", error: "#e24b4a", warn: "#f4a261", success: "#2d6a4f" };
    t.style.background = colors[type] || colors.info;
    t.textContent = message;
    t.style.opacity = "1";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.style.opacity = "0"; }, 4000);
  }
  window.agroToast = agroToast;

  // ───────────────────────────────────────────────
  // 4. OFFLINE BANNER
  // ───────────────────────────────────────────────
  function showOfflineBanner(text, color) {
    let b = document.getElementById("agro-offline-banner");
    if (!b) {
      b = document.createElement("div");
      b.id = "agro-offline-banner";
      b.style.cssText =
        "position:fixed;top:0;left:0;right:0;padding:8px 14px;text-align:center;" +
        "font-family:'Segoe UI',system-ui,sans-serif;font-size:13px;font-weight:600;" +
        "color:#fff;z-index:99998;transition:transform .25s;transform:translateY(-100%)";
      document.body.appendChild(b);
    }
    b.style.background = color || "#e24b4a";
    b.textContent = text;
    requestAnimationFrame(function () { b.style.transform = "translateY(0)"; });
  }
  function hideOfflineBanner() {
    const b = document.getElementById("agro-offline-banner");
    if (b) b.style.transform = "translateY(-100%)";
  }
  window.addEventListener("offline", function () {
    showOfflineBanner("📡 You're offline — changes may not save until you reconnect", "#e24b4a");
  });
  window.addEventListener("online", function () {
    showOfflineBanner("✅ Back online", "#2d6a4f");
    setTimeout(hideOfflineBanner, 2500);
  });
  // On load, if already offline, say so.
  if (!navigator.onLine) {
    document.addEventListener("DOMContentLoaded", function () {
      showOfflineBanner("📡 You're offline — changes may not save until you reconnect", "#e24b4a");
    });
  }

  // ───────────────────────────────────────────────
  // 3. FETCH WRAPPER
  //    Transparently adds: offline message, retry on
  //    network failure (GET only), 401 auto-logout,
  //    and a friendly toast when a request truly fails.
  // ───────────────────────────────────────────────
  const realFetch = window.fetch.bind(window);
  let redirecting = false;

  function isApiCall(url) {
    return typeof url === "string" && url.indexOf(API_HOST) !== -1;
  }
  function isAuthCall(url) {
    return typeof url === "string" && url.indexOf("/auth/") !== -1;
  }

  window.fetch = async function (resource, options) {
    options = options || {};
    const url = typeof resource === "string" ? resource : (resource && resource.url) || "";
    const method = (options.method || "GET").toUpperCase();
    const retriable = method === "GET" && isApiCall(url);
    const maxAttempts = retriable ? 3 : 1;

    let lastErr;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const res = await realFetch(resource, options);

        // 401 on an AUTHENTICATED call = session expired → log out.
        // (Skip /auth/ endpoints: a wrong password there is normal, not an expiry.)
        if (
          res.status === 401 &&
          isApiCall(url) &&
          !isAuthCall(url) &&
          localStorage.getItem("agro_token") &&
          !redirecting
        ) {
          redirecting = true;
          localStorage.removeItem("agro_token");
          agroToast("Your session expired — please log in again", "warn");
          const toLogin = location.pathname.indexOf("/pages/") !== -1 ? "../index.html" : "index.html";
          setTimeout(function () { window.location.href = toLogin; }, 1200);
        }
        return res;
      } catch (err) {
        // Network-level failure (offline, DNS, server unreachable, CORS abort)
        lastErr = err;
        if (attempt < maxAttempts) {
          await new Promise(function (r) { setTimeout(r, 700 * attempt); });
          continue;
        }
      }
    }

    // All attempts failed.
    if (isApiCall(url)) {
      if (!navigator.onLine) {
        showOfflineBanner("📡 You're offline — couldn't reach the server", "#e24b4a");
      } else {
        agroToast("Couldn't reach the server. Please try again.", "error");
      }
    }
    throw lastErr;
  };

  // ───────────────────────────────────────────────
  // 5. GLOBAL ERROR CATCHER  (the "error boundary")
  //    Logs everything; shows a quiet toast at most
  //    once every few seconds so it never spams.
  // ───────────────────────────────────────────────
  let lastErrorToast = 0;
  function reportError(label, detail) {
    console.error("[AgroTech] " + label, detail);
    const now = Date.now();
    if (now - lastErrorToast > 6000) {
      lastErrorToast = now;
      agroToast("Something went wrong. If it keeps happening, refresh the page.", "error");
    }
  }
  window.addEventListener("error", function (e) {
    reportError("JS error", e.message || e.error);
  });
  window.addEventListener("unhandledrejection", function (e) {
    reportError("Unhandled promise", e.reason);
  });

  // ───────────────────────────────────────────────
  // 6. PWA  (manifest + theme color + service worker)
  // ───────────────────────────────────────────────
  function ensureTag(create) {
    document.head.appendChild(create());
  }
  document.addEventListener("DOMContentLoaded", function () {
    if (!document.querySelector('link[rel="manifest"]')) {
      ensureTag(function () {
        const l = document.createElement("link");
        l.rel = "manifest";
        l.href = "/manifest.json";
        return l;
      });
    }
    if (!document.querySelector('meta[name="theme-color"]')) {
      ensureTag(function () {
        const m = document.createElement("meta");
        m.name = "theme-color";
        m.content = "#1a3d2b";
        return m;
      });
    }
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function (err) {
        console.warn("[AgroTech] Service worker registration failed:", err);
      });
    });
  }
})();
