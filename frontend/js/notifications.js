// ═══════════════════════════════════════════════════════════
//  AGROTECH NOTIFICATIONS SYSTEM
//  This file is shared by ALL pages.
//  It checks for:
//    - Overdue farm tasks
//    - Tasks due today
//    - Low stock / out of stock inventory items
//  Then shows:
//    - A red badge number on the 🔔 bell icon (topbar)
//    - Red badge numbers on sidebar menu items
//    - A dropdown list when the bell is clicked
// ═══════════════════════════════════════════════════════════

const NOTIF_API = "https://agrotech-75cy.onrender.com";

// Escape user text before putting it in innerHTML (XSS protection).
// Falls back to a local copy if app.js hasn't defined the shared one.
const esc = (window.escapeHtml) ? window.escapeHtml : function (v) {
  if (v === null || v === undefined) return "";
  return String(v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
                  .replace(/"/g,"&quot;").replace(/'/g,"&#039;");
};


// ═══════════════════════════════════════════════
//  SIDEBAR TOGGLE  (shared by all pages)
// ═══════════════════════════════════════════════
function toggleSidebar(){
  document.getElementById("sidebar")?.classList.toggle("open");
  document.getElementById("sidebar-overlay")?.classList.toggle("show");
}
function closeSidebar(){
  document.getElementById("sidebar")?.classList.remove("open");
  document.getElementById("sidebar-overlay")?.classList.remove("show");
}
// Close the menu after tapping a nav link on mobile
document.addEventListener("DOMContentLoaded", function(){
  document.querySelectorAll(".sb-nav a").forEach(function(a){
    a.addEventListener("click", function(){
      if (window.innerWidth <= 768) closeSidebar();
    });
  });
});


// ═══════════════════════════════════════════════
//  INJECT BELL ICON INTO TOPBAR
// ═══════════════════════════════════════════════
function injectNotificationBell() {
  const topbar = document.querySelector(".topbar");
  if (!topbar) return;
  if (document.getElementById("notif-bell")) return;

  const bellWrap = document.createElement("div");
  bellWrap.style.position = "relative";
  bellWrap.innerHTML = `
    <button id="notif-bell" onclick="toggleNotifDropdown()" style="
      position:relative;background:#fff;border:1.5px solid #d5e8da;
      border-radius:10px;width:42px;height:42px;cursor:pointer;
      font-size:20px;display:flex;align-items:center;justify-content:center;
      transition:all 0.15s;">
      🔔
      <span id="notif-badge" style="
        position:absolute;top:-6px;right:-6px;
        background:#e24b4a;color:#fff;font-size:11px;font-weight:800;
        min-width:20px;height:20px;border-radius:10px;
        display:none;align-items:center;justify-content:center;
        padding:0 5px;border:2px solid #fff;">0</span>
    </button>

    <div id="notif-dropdown" style="
      display:none;position:absolute;top:50px;right:0;
      background:#fff;border:1px solid #d5e8da;border-radius:12px;
      width:340px;max-height:420px;overflow-y:auto;
      box-shadow:0 8px 30px rgba(0,0,0,0.15);z-index:1000;">
      <div style="padding:14px 18px;border-bottom:1px solid #f0f4f1;display:flex;justify-content:space-between;align-items:center">
        <strong style="font-size:14px;color:#1a3d2b">🔔 Notifications</strong>
        <span id="notif-count-label" style="font-size:12px;color:#888"></span>
      </div>
      <div id="notif-list" style="padding:8px"></div>
    </div>
  `;

  // ── Figure out where to put the bell ──────────────
  // Some topbars have: [left info div] only
  // Some topbars have: [left info div] [button(s)]
  // We want the bell to sit on the far right, next to
  // any existing buttons, without breaking the layout.
  const topRight = topbar.querySelector(".topbar-right");

  if (topRight) {
    // Page already has a .topbar-right container — put bell first inside it
    topRight.insertBefore(bellWrap, topRight.firstChild);
    topRight.style.display = "flex";
    topRight.style.alignItems = "center";
    topRight.style.gap = "10px";
  } else if (topbar.children.length > 1) {
    // Topbar has a left info div + other elements (buttons etc.)
    // Wrap everything except the first child into one flex group with the bell
    const firstChild = topbar.children[0];
    const rest = Array.from(topbar.children).slice(1);

    const group = document.createElement("div");
    group.style.display = "flex";
    group.style.alignItems = "center";
    group.style.gap = "10px";
    group.style.marginLeft = "auto";

    group.appendChild(bellWrap);
    rest.forEach(el => group.appendChild(el));
    topbar.appendChild(group);
  } else {
    // Topbar only has the left info div — just append bell, push to the right
    bellWrap.style.marginLeft = "auto";
    topbar.appendChild(bellWrap);
  }
}


// ═══════════════════════════════════════════════
//  TOGGLE DROPDOWN
// ═══════════════════════════════════════════════
function toggleNotifDropdown() {
  const dd = document.getElementById("notif-dropdown");
  if (!dd) return;
  dd.style.display = dd.style.display === "block" ? "none" : "block";
}

document.addEventListener("click", function(e) {
  const bell = document.getElementById("notif-bell");
  const dd   = document.getElementById("notif-dropdown");
  if (!bell || !dd) return;
  if (!bell.contains(e.target) && !dd.contains(e.target)) {
    dd.style.display = "none";
  }
});


// ═══════════════════════════════════════════════
//  LOAD NOTIFICATIONS
// ═══════════════════════════════════════════════
async function loadNotifications() {
  const token = localStorage.getItem("agro_token");
  if (!token) return;

  const prefs = JSON.parse(localStorage.getItem("notif_prefs") || "null") || {
    tasks: true, stock: true, weather: true
  };

  const notifications = [];

  try {
    // ── TASKS ─────────────────────────────────
    if (prefs.tasks) {
      const tasks = await fetch(NOTIF_API+"/tasks", {
        headers: {"Authorization":"Bearer "+token}
      }).then(r=>r.json());

      const today = new Date().toISOString().split("T")[0];
      const overdue  = tasks.filter(t => !t.done && t.overdue);
      const dueToday = tasks.filter(t => !t.done && !t.overdue && t.scheduledDate === today);

      overdue.forEach(t => {
        notifications.push({
          icon: "🚨", type: "danger",
          title: "Overdue: " + esc(t.title),
          sub: (t.cropName ? esc(t.cropName)+" · " : "") + "Was due " + formatDate(t.scheduledDate),
          link: "schedule.html"
        });
      });

      dueToday.forEach(t => {
        notifications.push({
          icon: "⏰", type: "warn",
          title: "Due today: " + esc(t.title),
          sub: (t.cropName ? esc(t.cropName)+" · " : "") + "Scheduled for today",
          link: "schedule.html"
        });
      });

      setSidebarBadge("schedule.html", overdue.length + dueToday.length, overdue.length > 0);
    }

    // ── INVENTORY ─────────────────────────────
    if (prefs.stock) {
      const items = await fetch(NOTIF_API+"/inventory", {
        headers: {"Authorization":"Bearer "+token}
      }).then(r=>r.json());

      const out = items.filter(i => i.isOut);
      const low = items.filter(i => i.isLow && !i.isOut);

      out.forEach(i => {
        notifications.push({
          icon: "🚨", type: "danger",
          title: "Out of stock: " + esc(i.name),
          sub: "You have 0 " + esc(i.unit) + " left",
          link: "inventory.html"
        });
      });

      low.forEach(i => {
        notifications.push({
          icon: "⚠️", type: "warn",
          title: "Low stock: " + esc(i.name),
          sub: i.quantity + " " + esc(i.unit) + " left (alert at " + i.lowAt + ")",
          link: "inventory.html"
        });
      });

      setSidebarBadge("inventory.html", out.length + low.length, out.length > 0);
    }

  } catch(e) {
    console.error("Notification load error:", e);
  }

  renderNotifications(notifications);
}


// ═══════════════════════════════════════════════
//  SET SIDEBAR BADGE
// ═══════════════════════════════════════════════
function setSidebarBadge(href, count, urgent) {
  const link = document.querySelector(`.sb-nav a[href="${href}"]`);
  if (!link) return;

  const existing = link.querySelector(".sidebar-badge");
  if (existing) existing.remove();

  if (count <= 0) return;

  const badge = document.createElement("span");
  badge.className = "sidebar-badge";
  badge.textContent = count > 9 ? "9+" : count;
  badge.style.cssText = `
    margin-left:auto;background:${urgent ? '#e24b4a' : '#f4a261'};
    color:#fff;font-size:11px;font-weight:800;
    min-width:20px;height:20px;border-radius:10px;
    display:flex;align-items:center;justify-content:center;
    padding:0 5px;
  `;
  link.appendChild(badge);
}


// ═══════════════════════════════════════════════
//  RENDER NOTIFICATION DROPDOWN + BELL BADGE
// ═══════════════════════════════════════════════
function renderNotifications(notifications) {
  const badge = document.getElementById("notif-badge");
  const list  = document.getElementById("notif-list");
  const countLabel = document.getElementById("notif-count-label");

  if (!badge || !list) return;

  notifications.sort((a,b) => {
    const order = {danger:0, warn:1, info:2};
    return order[a.type] - order[b.type];
  });

  if (notifications.length > 0) {
    badge.textContent = notifications.length > 9 ? "9+" : notifications.length;
    badge.style.display = "flex";
  } else {
    badge.style.display = "none";
  }

  countLabel.textContent = notifications.length + " alert" + (notifications.length!==1?"s":"");

  if (!notifications.length) {
    list.innerHTML = `
      <div style="text-align:center;padding:30px 16px;color:#aaa">
        <div style="font-size:36px;margin-bottom:8px">✅</div>
        <div style="font-size:14px;font-weight:600;color:#666">All caught up!</div>
        <div style="font-size:12px;margin-top:4px">No urgent alerts right now</div>
      </div>`;
    return;
  }

  const typeColors = {
    danger: { bg:"#fcebeb", border:"#f09595" },
    warn:   { bg:"#fff8e1", border:"#ffe082" },
    info:   { bg:"#e3f2fd", border:"#bbdefb" }
  };

  list.innerHTML = notifications.map(n => {
    const col = typeColors[n.type] || typeColors.info;
    return `
      <a href="${n.link}" style="
        display:flex;gap:12px;align-items:flex-start;
        padding:12px;border-radius:8px;margin-bottom:4px;
        text-decoration:none;color:inherit;
        background:${col.bg};border:1px solid ${col.border};
        transition:opacity 0.15s;" onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">
        <span style="font-size:20px;flex-shrink:0">${n.icon}</span>
        <div>
          <div style="font-size:13px;font-weight:700;color:#1a3d2b">${n.title}</div>
          <div style="font-size:12px;color:#888;margin-top:2px">${n.sub}</div>
        </div>
      </a>`;
  }).join("");
}


// ═══════════════════════════════════════════════
//  HELPER — format date nicely
// ═══════════════════════════════════════════════
function formatDate(dateStr) {
  const d = new Date(dateStr+"T00:00:00");
  const today = new Date();
  const diffDays = Math.round((today - d) / 86400000);

  if (diffDays === 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays > 1)   return diffDays + " days ago";
  return d.toLocaleDateString("en-KE",{day:"numeric",month:"short"});
}


// ═══════════════════════════════════════════════
//  INITIALISE
// ═══════════════════════════════════════════════
document.addEventListener("DOMContentLoaded", function() {
  injectNotificationBell();
  loadNotifications();
  setInterval(loadNotifications, 60000);
});
