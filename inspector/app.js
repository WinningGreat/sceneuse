const statusEl = document.getElementById("status");
const metaEl = document.getElementById("meta");
const windowsEl = document.getElementById("windows");
const nodesEl = document.getElementById("nodes");
const promptEl = document.getElementById("prompt");
const canvas = document.getElementById("plane");
const ctx = canvas.getContext("2d");

let selectedNode = null;
const tileCache = new Map();

function nodeLine(n) {
  if ((n.role === "group" || n.role === "unknown") && !n.name) return null;
  const name = n.name ? ` "${n.name}"` : "";
  const value = n.value != null && n.value !== "" ? ` value=${JSON.stringify(n.value)}` : "";
  const tags = n.tags || [];
  const mark = tags.includes("target") ? "*" : " ";
  const hint = tags.length ? `  (${tags.join(", ")})` : "";
  return `  ${mark}[${n.id}] ${n.role}${name}${value}${hint}`;
}

function renderPrompt(scene) {
  if (!scene) return "";
  const d0 = (scene.displays || [])[0];
  const b = (d0 && d0.bounds) || { w: 0, h: 0 };
  const scale = (d0 && d0.scale) || 1;
  const focus = scene.focus || {};
  const observe = scene.observe || focus;
  const damage = scene.damage || [];
  const nodes = scene.nodes || [];
  const tiles = scene.tiles || [];
  const lines = [
    `display ${d0 ? d0.id : "0"} ${Math.round(b.w)}x${Math.round(b.h)} @${scale}x`,
    `focus: ${focus.app || "?"}  pid=${focus.pid ?? "?"}  win=${focus.window || "?"}`,
    `observe: ${observe.app || "?"}  win=${observe.window || "?"}`,
    `damage: ${damage.length} rect${damage.length === 1 ? "" : "s"}`,
  ];
  const important = nodes.filter((n) => (n.tags || []).length);
  important.sort((a, b) => {
    const rank = (n) => {
      const t = n.tags || [];
      return (t.includes("target") ? 0 : 1) + (t.includes("focus") ? 0 : 1);
    };
    return rank(a) - rank(b);
  });
  if (important.length) {
    lines.push("important:");
    for (const n of important.slice(0, 12)) {
      const line = nodeLine(n);
      if (line) lines.push(line);
    }
  }
  lines.push("nodes:");
  let shown = 0;
  for (const n of nodes) {
    const line = nodeLine(n);
    if (!line) continue;
    lines.push(line);
    shown += 1;
    if (shown >= 60) break;
  }
  if (shown === 0) lines.push("  (none)");
  lines.push(tiles.length ? `tiles: ${tiles.length}` : "tiles: none");
  return lines.join("\n");
}

function draw(scene) {
  const displays = scene.displays || [];
  const d0 = displays[0] || { bounds: { x: 0, y: 0, w: 1470, h: 956 } };
  const b = d0.bounds;
  const w = Math.max(1, Math.round(b.w));
  const h = Math.max(1, Math.round(b.h));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  ctx.fillStyle = "#0c0b0a";
  ctx.fillRect(0, 0, w, h);

  for (const win of scene.windows || []) {
    const r = win.bounds;
    if (!r) continue;
    ctx.strokeStyle = win.focused ? "#7ec8a3" : "#3a362f";
    ctx.lineWidth = win.focused ? 2 : 1;
    ctx.strokeRect(r.x - b.x, r.y - b.y, r.w, r.h);
    ctx.fillStyle = win.focused ? "rgba(126,200,163,0.06)" : "rgba(255,255,255,0.02)";
    ctx.fillRect(r.x - b.x, r.y - b.y, r.w, r.h);
    ctx.fillStyle = "#8a8476";
    ctx.font = "11px ui-monospace, monospace";
    ctx.fillText((win.app || "") + (win.title ? " — " + win.title : ""), r.x - b.x + 6, r.y - b.y + 14);
  }

  for (const tile of scene.tiles || []) {
    const r = tile.rect;
    const key = tile.data && tile.data.slice(0, 48);
    let img = tileCache.get(key);
    if (!img && tile.data) {
      img = new Image();
      img.src = `data:${tile.mime || "image/jpeg"};base64,${tile.data}`;
      tileCache.set(key, img);
    }
    if (img && img.complete) {
      ctx.drawImage(img, r.x - b.x, r.y - b.y, r.w, r.h);
    } else {
      ctx.fillStyle = "rgba(110,168,217,0.25)";
      ctx.fillRect(r.x - b.x, r.y - b.y, r.w, r.h);
    }
    ctx.strokeStyle = "#6ea8d9";
    ctx.strokeRect(r.x - b.x, r.y - b.y, r.w, r.h);
  }

  for (const r of scene.damage || []) {
    ctx.strokeStyle = "#e6a23c";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(r.x - b.x + 0.5, r.y - b.y + 0.5, r.w, r.h);
    ctx.fillStyle = "rgba(230,162,60,0.10)";
    ctx.fillRect(r.x - b.x, r.y - b.y, r.w, r.h);
  }

  const cur = scene.cursor;
  if (cur) {
    ctx.fillStyle = "#ece7dc";
    ctx.beginPath();
    ctx.moveTo(cur.x - b.x, cur.y - b.y);
    ctx.lineTo(cur.x - b.x + 10, cur.y - b.y + 14);
    ctx.lineTo(cur.x - b.x + 4, cur.y - b.y + 14);
    ctx.closePath();
    ctx.fill();
  }
}

function listWindows(scene) {
  windowsEl.innerHTML = "";
  for (const win of scene.windows || []) {
    const li = document.createElement("li");
    li.className = "win" + (win.focused ? " focus" : "") + (win.id === (scene.observe && scene.observe.window) ? " observe" : "");
    li.innerHTML = `<span class="title">${escapeHtml(win.app || win.id)}</span>
      <span class="sub">${escapeHtml(win.title || win.id)} · z${win.z}${win.occluded ? " · occluded" : ""}</span>`;
    windowsEl.appendChild(li);
  }
}

function listNodes(scene) {
  nodesEl.innerHTML = "";
  for (const n of scene.nodes || []) {
    if ((n.role === "group" || n.role === "unknown") && !n.name) continue;
    const li = document.createElement("li");
    li.className = "node"
      + (selectedNode === n.id ? " selected" : "")
      + ((n.tags || []).includes("target") ? " target" : "")
      + ((n.tags || []).includes("focus") ? " focus-node" : "");
    const name = n.name ? ` “${n.name}”` : "";
    const tags = (n.tags || []).join(" ");
    li.innerHTML = `<span class="title">${n.id} · ${n.role}${escapeHtml(name)}</span>
      <span class="sub">${tags ? tags + " · " : ""}${(n.actions || []).join(" ") || "no actions"}</span>`;
    li.addEventListener("click", () => {
      selectedNode = n.id;
      if ((n.actions || []).includes("press")) {
        fetch("/api/act", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ op: "invoke", node: n.id, action: "press" }),
        }).catch(() => {});
      }
      listNodes(scene);
    });
    nodesEl.appendChild(li);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function tick() {
  try {
    const res = await fetch("/api/scene");
    const data = await res.json();
    if (!data.connected) {
      statusEl.textContent = data.error ? `offline · ${data.error}` : "waiting for daemon";
      statusEl.classList.add("bad");
      return;
    }
    statusEl.textContent = "live";
    statusEl.classList.remove("bad");
    const scene = data.scene;
    if (!scene) return;
    const tiles = scene.tiles || [];
    metaEl.textContent = `seq ${scene.seq} · ${scene.kind} · damage ${ (scene.damage || []).length } · tiles ${tiles.length}`;
    promptEl.textContent = renderPrompt(scene);
    listWindows(scene);
    listNodes(scene);
    draw(scene);
  } catch (err) {
    statusEl.textContent = "inspector error";
    statusEl.classList.add("bad");
  }
}

setInterval(tick, 160);
tick();
