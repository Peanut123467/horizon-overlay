/* Horizon control panel -- vanilla JS, no build step. */

/* Surfaced for the smoke test in tools/console_smoke.py: WebView2 renders via
   DirectComposition, so screen capture cannot see this window and DOM state is
   the only way to assert the page works. */
window.__horizonErrors = [];
window.addEventListener("error", (event) => {
  window.__horizonErrors.push(String(event.message || event.error));
});

const PALETTE = ["#00FF66", "#00E5FF", "#FFFFFF", "#FFD60A", "#B388FF"];

const SCHEMA = [
  {
    key: "vignette",
    label: "暗角",
    desc: "压暗画面四周，减少周边视野里的光流",
    fields: [
      { name: "enabled", type: "switch", label: "启用" },
      { name: "inner", label: "起始半径", type: "range", min: 0, max: 2, step: 0.01 },
      { name: "outer", label: "最大半径", type: "range", min: 0, max: 3, step: 0.01 },
      { name: "strength", label: "强度", type: "range", min: 0, max: 1, step: 0.01 },
    ],
  },
  {
    key: "frame",
    label: "边框",
    desc: "一圈固定的参照边缘，不随镜头移动",
    fields: [
      { name: "enabled", type: "switch", label: "启用" },
      { name: "inset", label: "距屏幕边缘", type: "range", min: 0, max: 400, step: 1, unit: "px" },
      { name: "width", label: "粗细", type: "range", min: 1, max: 60, step: 1, unit: "px" },
      { name: "alpha", label: "不透明度", type: "range", min: 0, max: 255, step: 1 },
    ],
  },
  {
    key: "triangles",
    label: "四边三角",
    desc: "四边固定的 V 形参照，大小统一调节，颜色跟随全局设置",
    fields: [
      { name: "enabled", type: "switch", label: "启用" },
      { name: "filled", label: "样式", type: "select", boolean: true, options: [["false", "空心"], ["true", "实心"]] },
      { name: "base", label: "底边宽度", type: "range", min: 1, max: 100, step: 1, unit: "%" },
      { name: "depth", label: "伸入深度", type: "range", min: 1, max: 100, step: 1, unit: "%" },
      { name: "width", label: "空心线宽", type: "range", min: 1, max: 60, step: 1, unit: "px" },
      { name: "alpha", label: "不透明度", type: "range", min: 0, max: 255, step: 1, percentOf: 255 },
    ],
  },
  {
    key: "reticle",
    label: "中心准星",
    desc: "屏幕正中的四个短刻度，给眼睛一个锚点",
    fields: [
      { name: "enabled", type: "switch", label: "启用" },
      { name: "size", label: "刻度长度", type: "range", min: 1, max: 80, step: 1, unit: "px" },
      { name: "gap", label: "中心留空", type: "range", min: 0, max: 80, step: 1, unit: "px" },
      { name: "alpha", label: "不透明度", type: "range", min: 0, max: 255, step: 1 },
    ],
  },
  {
    key: "grid",
    label: "锚点阵",
    desc: "均匀分布的小点，适合需要更多参照的情况",
    fields: [
      { name: "enabled", type: "switch", label: "启用" },
      { name: "spacing", label: "点间距", type: "range", min: 24, max: 2000, step: 1, unit: "px" },
      { name: "radius", label: "点大小", type: "range", min: 1, max: 20, step: 1, unit: "px" },
      { name: "alpha", label: "不透明度", type: "range", min: 0, max: 255, step: 1 },
    ],
  },
  {
    key: "stats",
    label: "统计面板",
    desc: "刷新率、本程序内存、系统内存、上次重绘耗时",
    fields: [
      { name: "enabled", type: "switch", label: "启用" },
      {
        name: "position",
        label: "位置",
        type: "select",
        options: [
          ["top-left", "左上"],
          ["top-right", "右上"],
          ["bottom-left", "左下"],
          ["bottom-right", "右下"],
        ],
      },
      { name: "font_size", label: "字号", type: "range", min: 9, max: 48, step: 1, unit: "px" },
      { name: "alpha", label: "背景不透明度", type: "range", min: 0, max: 255, step: 1 },
      { name: "refresh_ms", label: "刷新间隔", type: "range", min: 250, max: 10000, step: 1, unit: "ms" },
    ],
  },
  {
    key: "session",
    label: "休息提醒",
    desc: "连续游玩到设定时长后，在画面底部提示起身活动",
    fields: [
      { name: "enabled", type: "switch", label: "启用" },
      { name: "minutes", label: "提醒间隔", type: "range", min: 1, max: 600, step: 1, unit: " 分钟" },
      { name: "reminder_seconds", label: "提示停留", type: "range", min: 3, max: 120, step: 1, unit: " 秒" },
    ],
  },
];

let api = null;
let cfg = null;
let patchTimer = null;
let previewTimer = null;
let patchFlight = null;
let previewInFlight = false;
let previewPending = false;
let editRevision = 0;
let monitors = [];
let hotkeyLabels = {};
let serial = Promise.resolve();
const pendingPatch = {};
const drawerStates = new Map();
let activeSelect = null;
let selectSerial = 0;

document.addEventListener("pointerdown", (event) => {
  if (activeSelect && !activeSelect.contains(event.target)) activeSelect.close(false);
});
document.addEventListener("scroll", (event) => {
  if (activeSelect && !activeSelect.menu.contains(event.target)) activeSelect.close(false);
}, true);
window.addEventListener("resize", () => activeSelect?.close(false));
window.addEventListener("blur", () => activeSelect?.close(false));

function decorateSelects(controls) {
  for (const select of controls.querySelectorAll("select")) {
    const wrapper = document.createElement("div");
    wrapper.className = "select-control";
    select.replaceWith(wrapper);
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "select-trigger";
    trigger.setAttribute("role", "combobox");
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    const label = select.closest(".field")?.querySelector("label") || wrapper.closest(".field").querySelector("label");
    if (select.id) {
      trigger.id = select.id;
      select.id += "-native";
    } else {
      trigger.id = `select-trigger-${++selectSerial}`;
      if (label) label.htmlFor = trigger.id;
    }
    select.hidden = true;
    select.tabIndex = -1;
    const valueText = document.createElement("span");
    const chevron = document.createElement("span");
    chevron.className = "select-chevron";
    chevron.setAttribute("aria-hidden", "true");
    trigger.append(valueText, chevron);
    wrapper.append(select, trigger);
    let menu = null;
    let motion = null;
    let highlighted = 0;

    function updateLabel() {
      valueText.textContent = select.selectedOptions[0]?.textContent || "请选择";
      trigger.setAttribute("aria-label", `${label?.textContent || "选项"}：${valueText.textContent}`);
    }
    updateLabel();
    select.addEventListener("change", updateLabel);

    function close(restoreFocus = false) {
      if (!menu) return;
      const oldMenu = menu;
      const computed = getComputedStyle(oldMenu);
      const from = {clipPath: computed.clipPath, transform: computed.transform, opacity: computed.opacity};
      if (motion) motion.cancel();
      menu = null;
      if (activeSelect?.trigger === trigger) activeSelect = null;
      trigger.setAttribute("aria-expanded", "false");
      trigger.removeAttribute("aria-activedescendant");
      oldMenu.inert = true;
      oldMenu.style.pointerEvents = "none";
      if (restoreFocus) trigger.focus({preventScroll: true});
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
        oldMenu.remove();
      } else {
        const above = oldMenu.dataset.above === "true";
        const end = {clipPath: above ? "inset(100% 0 0 0)" : "inset(0 0 100% 0)", transform: `translateY(${above ? 10 : -10}px)`, opacity: 0};
        const cleanupTimer = setTimeout(() => oldMenu.remove(), 450);
        const cleanup = () => { clearTimeout(cleanupTimer); oldMenu.remove(); };
        oldMenu.animate([from, end], {duration: 300, easing: "cubic-bezier(.4,0,.3,1)", fill: "forwards"}).finished.then(cleanup).catch(cleanup);
      }
    }

    function highlight(index) {
      if (!menu) return;
      highlighted = (index + select.options.length) % select.options.length;
      menu.querySelectorAll(".select-option").forEach((option, i) => option.classList.toggle("highlighted", i === highlighted));
      const option = menu.children[highlighted];
      trigger.setAttribute("aria-activedescendant", option.id);
      // Scroll the popup itself without scrolling the panel and closing it.
      if (option.offsetTop < menu.scrollTop) menu.scrollTop = option.offsetTop;
      if (option.offsetTop + option.offsetHeight > menu.scrollTop + menu.clientHeight) menu.scrollTop = option.offsetTop + option.offsetHeight - menu.clientHeight;
    }

    function choose(index) {
      select.selectedIndex = index;
      select.dispatchEvent(new Event("change", {bubbles: true}));
      close(true);
    }

    function open() {
      if (trigger.disabled || !select.options.length) return;
      activeSelect?.close(false);
      menu = document.createElement("div");
      menu.className = "select-popup";
      menu.id = `select-list-${++selectSerial}`;
      menu.setAttribute("role", "listbox");
      menu.setAttribute("aria-label", label?.textContent || "选项");
      trigger.setAttribute("aria-controls", menu.id);
      trigger.setAttribute("aria-expanded", "true");
      [...select.options].forEach((item, index) => {
        const option = document.createElement("div");
        option.className = "select-option";
        option.id = `${menu.id}-${index}`;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", String(index === select.selectedIndex));
        option.textContent = item.textContent;
        option.addEventListener("pointerdown", (event) => event.preventDefault());
        option.addEventListener("pointermove", () => highlight(index));
        option.addEventListener("click", () => choose(index));
        menu.appendChild(option);
      });
      document.body.appendChild(menu);
      const rect = trigger.getBoundingClientRect();
      const below = innerHeight - rect.bottom - 12;
      const above = rect.top - 12;
      const desired = Math.min(260, select.options.length * 38 + 12);
      const openAbove = below < desired && above > below;
      const width = Math.min(rect.width, innerWidth - 24);
      menu.dataset.above = String(openAbove);
      menu.style.width = `${width}px`;
      menu.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`;
      menu.style.maxHeight = `${Math.max(38, Math.min(260, openAbove ? above : below))}px`;
      const height = menu.getBoundingClientRect().height;
      menu.style.top = `${Math.max(6, openAbove ? rect.top - height - 6 : rect.bottom + 6)}px`;
      activeSelect = {trigger, menu, close, contains: (node) => wrapper.contains(node) || menu?.contains(node)};
      highlight(Math.max(0, select.selectedIndex));
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
        motion = menu.animate([
          {clipPath: openAbove ? "inset(100% 0 0 0)" : "inset(0 0 100% 0)", transform: `translateY(${openAbove ? 12 : -12}px)`, opacity: 0},
          {clipPath: "inset(0 0 0 0)", transform: "translateY(0)", opacity: 1},
        ], {duration: 420, easing: "cubic-bezier(.22,.8,.25,1)"});
      }
    }
    trigger.addEventListener("click", () => menu ? close() : open());
    trigger.addEventListener("keydown", (event) => {
      if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " ", "Escape"].includes(event.key)) {
        event.preventDefault();
        if (event.key === "Escape") { close(); return; }
        if (!menu) { open(); return; }
        if (event.key === "ArrowDown") highlight(highlighted + 1);
        else if (event.key === "ArrowUp") highlight(highlighted - 1);
        else if (event.key === "Home") highlight(0);
        else if (event.key === "End") highlight(select.options.length - 1);
        else choose(highlighted);
      } else if (event.key === "Tab") close();
    });
    trigger.addEventListener("blur", () => close());
  }
}

// Delegate to cover controls recreated after presets, imports and tray updates.
document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (button._jelly) button._jelly.cancel();
  button._jelly = button.animate([
    { transform: "scale(1)" },
    { transform: "scale(.94, 1.06)", offset: .20 },
    { transform: "scale(1.05, .95)", offset: .43 },
    { transform: "scale(.98, 1.02)", offset: .65 },
    { transform: "scale(1.01, .99)", offset: .83 },
    { transform: "scale(1)" },
  ], { duration: 780, easing: "cubic-bezier(.22,.75,.25,1)" });
}, true);

const $ = (sel) => document.querySelector(sel);

/* ------------------------------------------------------------ utilities */

function setStatus(alive) {
  const badge = $("#status");
  const startBtn = $("#btn-start");
  $("#btn-stop").hidden = !alive;
  $("#btn-toggle").hidden = !alive;
  if (alive) {
    badge.textContent = "叠加层运行中";
    badge.className = "badge badge-ok";
    startBtn.hidden = true;
  } else {
    badge.textContent = "叠加层未运行";
    badge.className = "badge badge-warn";
    startBtn.hidden = false;
  }
}

function formatValue(value, field) {
  const num = Number(value);
  if (field.percentOf) return `${Math.round(num / field.percentOf * 100)}%`;
  const text = Number.isInteger(num) ? String(num) : num.toFixed(2);
  return field.unit ? text + field.unit : text;
}

function setAccent(hex) {
  document.documentElement.style.setProperty("--accent", hex);
}

/* --------------------------------------------------------------- patching */

function queuePatch(patch) {
  for (const [key, value] of Object.entries(patch)) {
    if (value && typeof value === "object") {
      pendingPatch[key] = Object.assign(pendingPatch[key] || {}, value);
    } else {
      pendingPatch[key] = value;
    }
  }
  if (patchTimer === null && !patchFlight) {
    patchTimer = setTimeout(() => {
      patchTimer = null;
      // enqueue reports API errors; consume the timer callback's rejection.
      flushPatch().catch(() => {});
    }, 50);
  }
}

function flushPatch() {
  clearTimeout(patchTimer);
  patchTimer = null;
  if (patchFlight) return patchFlight;
  if (!Object.keys(pendingPatch).length) return serial;
  patchFlight = (async () => {
    while (Object.keys(pendingPatch).length) {
      const body = Object.assign({}, pendingPatch);
      for (const key of Object.keys(pendingPatch)) delete pendingPatch[key];
      await enqueue(async () => {
        const state = await api.patch(body);
        setStatus(state.overlay_alive);
      });
    }
  })().finally(() => {
    patchFlight = null;
    if (Object.keys(pendingPatch).length) queuePatch({});
  });
  return patchFlight;
}

function enqueue(work) {
  const task = serial.then(work);
  serial = task.catch((err) => { showError(err); });
  return task;
}

function showError(err) {
  window.__horizonErrors.push(String(err));
  const el = $("#feedback");
  el.className = "error";
  el.textContent = "操作失败：" + (err.message || err);
}

function notify(text) {
  const el = $("#feedback");
  el.className = "";
  el.textContent = text;
  setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 3500);
}

function queuePreview() {
  previewPending = true;
  if (!previewInFlight && previewTimer === null) {
    previewTimer = setTimeout(refreshPreview, 33);
  }
}

async function refreshPreview() {
  previewTimer = null;
  previewPending = false;
  previewInFlight = true;
  try {
    const src = await api.preview(cfg);
    // Display intermediate frames too: continuous input must not starve painting.
    $("#preview").src = src;
  } catch (err) {
    showError(err);
  } finally {
    previewInFlight = false;
    if (previewPending) queuePreview();
  }
}

function setValue(group, name, value) {
  editRevision++;
  markActivePreset();
  if (group) cfg[group][name] = value;
  else cfg[name] = value;
  if (group === "triangles") refreshDisabled();
  queuePatch(group ? { [group]: { [name]: value } } : { [name]: value });
  queuePreview();
}

/* --------------------------------------------------------------- rendering */

function makeSwitch(checked, onChange) {
  const input = document.createElement("input");
  input.type = "checkbox";
  input.className = "switch";
  input.checked = checked;
  input.addEventListener("change", () => onChange(input.checked));
  return input;
}

function makeField(group, field) {
  const row = document.createElement("div");
  row.className = "field";
  row.dataset.group = group.key;
  row.dataset.field = field.name;

  const label = document.createElement("label");
  label.textContent = field.label;
  label.htmlFor = `${group.key}-${field.name}`;
  row.appendChild(label);

  if (field.type === "select") {
    const select = document.createElement("select");
    select.id = label.htmlFor;
    for (const [value, text] of field.options) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      select.appendChild(option);
    }
    select.value = cfg[group.key][field.name];
    select.addEventListener("change", () => setValue(
      group.key, field.name, field.boolean ? select.value === "true" : select.value
    ));
    row.appendChild(select);

    const spacer = document.createElement("span");
    row.appendChild(spacer);
    return row;
  }

  const input = document.createElement("input");
  input.type = "range";
  input.id = label.htmlFor;
  input.min = field.min;
  input.max = field.max;
  input.step = field.step;
  input.value = cfg[group.key][field.name];

  const out = document.createElement("output");
  out.textContent = formatValue(input.value, field);

  input.addEventListener("input", () => {
    out.textContent = formatValue(input.value, field);
    setValue(group.key, field.name, Number(input.value));
  });

  row.appendChild(input);
  row.appendChild(out);
  return row;
}

function makeGroup(group) {
  const el = document.createElement("section");
  el.className = "group";
  el.dataset.group = group.key;

  const head = document.createElement("div");
  head.className = "group-head";
  const title = document.createElement("h3");
  title.textContent = group.label;
  head.appendChild(title);

  if (group.fields.some((f) => f.name === "enabled")) {
    head.appendChild(
      makeSwitch(cfg[group.key].enabled, (checked) => {
        setValue(group.key, "enabled", checked);
        refreshDisabled();
      })
    );
  }
  el.appendChild(head);

  const desc = document.createElement("p");
  desc.className = "group-desc";
  desc.textContent = group.desc;
  el.appendChild(desc);

  for (const field of group.fields) {
    if (field.name === "enabled") continue;
    el.appendChild(makeField(group, field));
  }
  return el;
}

function makeMonitorGroup(monitors) {
  const el = document.createElement("section");
  el.className = "group";
  el.dataset.group = "display";

  const head = document.createElement("div");
  head.className = "group-head";
  const title = document.createElement("h3");
  title.textContent = "显示器";
  head.appendChild(title);
  el.appendChild(head);

  const desc = document.createElement("p");
  desc.className = "group-desc";
  desc.textContent = "叠加层一次只覆盖一个显示器，切换后即时生效";
  el.appendChild(desc);

  const row = document.createElement("div");
  row.className = "field";
  const label = document.createElement("label");
  label.textContent = "目标显示器";
  const select = document.createElement("select");
  for (const monitor of monitors) {
    const option = document.createElement("option");
    option.value = String(monitor.index);
    option.textContent = `${monitor.width} × ${monitor.height}${monitor.index === 0 ? "（主屏）" : ""}`;
    select.appendChild(option);
  }
  select.value = String(cfg.monitor);
  select.addEventListener("change", () => setValue(null, "monitor", Number(select.value)));
  row.appendChild(label);
  row.appendChild(select);
  row.appendChild(document.createElement("span"));
  el.appendChild(row);
  return el;
}

function refreshDisabled() {
  for (const group of SCHEMA) {
    const el = document.querySelector(`.group[data-group="${group.key}"]`);
    if (!el) continue;
    const on = cfg[group.key].enabled;
    for (const row of el.querySelectorAll(".field")) {
      const disabled = !on || (group.key === "triangles" && row.dataset.field === "width" && cfg.triangles.filled);
      row.classList.toggle("disabled", disabled);
      row.querySelectorAll("input,select,button").forEach((input) => { input.disabled = disabled; });
    }
  }
}

function markActivePreset() {
  document.querySelectorAll(".btn-preset").forEach((btn) => btn.classList.remove("active"));
}

function renderSwatches() {
  const box = $("#swatches");
  box.innerHTML = "";
  for (const hex of PALETTE) {
    const btn = document.createElement("button");
    btn.className = "swatch";
    btn.style.background = hex;
    btn.title = hex;
    if (cfg.color.toUpperCase() === hex.toUpperCase()) btn.classList.add("active");
    btn.addEventListener("click", () => applyColour(hex));
    box.appendChild(btn);
  }
  $("#colour-input").value = cfg.color;
  $("#colour-label").textContent = cfg.color;
}

function applyColour(hex) {
  cfg.color = hex;
  setAccent(hex);
  setValue(null, "color", hex);
  renderSwatches();
}

/* -------------------------------------------------------------------- boot */

function renderState(state) {
  if (activeSelect) activeSelect.close(false);
  cfg = state.config;
  setAccent(cfg.color);
  setStatus(state.overlay_alive);
  const controls = $("#controls");
  controls.innerHTML = "";
  for (const group of SCHEMA) controls.appendChild(makeGroup(group));
  if (monitors.length) controls.appendChild(makeMonitorGroup(monitors));
  controls.appendChild(makeHotkeyGroup());
  decorateDrawers(controls);
  decorateSelects(controls);
  refreshDisabled();
  renderSwatches();
  $("#start-hidden").checked = cfg.start_hidden;
  markActivePreset();
  queuePreview();
}

function decorateDrawers(controls) {
  for (const section of controls.querySelectorAll(".group")) {
    const key = section.dataset.group;
    let head = section.querySelector(".group-head");
    if (!head) {
      head = document.createElement("div");
      head.className = "group-head";
      head.appendChild(section.querySelector("h3"));
      section.prepend(head);
    }
    const title = head.querySelector("h3");
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "group-toggle";
    const text = document.createElement("span");
    text.textContent = title.textContent;
    const chevron = document.createElement("span");
    chevron.className = "drawer-chevron";
    chevron.setAttribute("aria-hidden", "true");
    toggle.append(text, chevron);
    title.replaceWith(toggle);
    const body = document.createElement("div");
    body.className = "group-body";
    body.id = `drawer-${key}`;
    const inner = document.createElement("div");
    inner.className = "drawer-inner";
    for (const child of [...section.children]) {
      if (child !== head) inner.appendChild(child);
    }
    body.appendChild(inner);
    section.appendChild(body);
    toggle.setAttribute("aria-controls", body.id);
    function setExpanded(expanded) {
      drawerStates.set(key, expanded);
      toggle.setAttribute("aria-expanded", String(expanded));
      section.classList.toggle("collapsed", !expanded);
      inner.inert = !expanded;
    }
    setExpanded(drawerStates.get(key) !== false);
    toggle.addEventListener("click", () => setExpanded(!drawerStates.get(key)));
  }
}

function makeHotkeyGroup() {
  const section = document.createElement("section");
  section.className = "group";
  section.dataset.group = "hotkeys";
  section.innerHTML = '<h3>快捷键</h3><p class="group-desc">点击键位后按组合键录制。使用 Ctrl 加字母、数字或 F1–F12；Esc 取消。</p>';
  for (const [action, title] of Object.entries(hotkeyLabels)) {
    const row = document.createElement("label");
    row.className = "hotkey-row";
    const label = document.createElement("span");
    label.textContent = title;
    const button = document.createElement("button");
    button.className = "btn";
    button.textContent = cfg.hotkeys[action];
    button.dataset.action = action;
    button.addEventListener("click", () => { button.textContent = "请按组合键…"; button.dataset.recording = "true"; });
    button.addEventListener("blur", () => { button.dataset.recording = "false"; button.textContent = cfg.hotkeys[action]; });
    button.addEventListener("keydown", async (event) => {
      if (button.dataset.recording !== "true") return;
      event.preventDefault();
      if (event.key === "Escape") { button.blur(); return; }
      if (["Control", "Alt", "Shift", "Meta"].includes(event.key)) return;
      const key = /^Key[A-Z]$/.test(event.code) ? event.code.slice(3) : /^Digit[0-9]$/.test(event.code) ? event.code.slice(5) : event.key;
      const value = [event.ctrlKey && "Ctrl", event.altKey && "Alt", event.shiftKey && "Shift", key.toUpperCase()].filter(Boolean).join("+");
      button.dataset.recording = "false";
      button.disabled = true;
      try {
        await flushPatch();
        await enqueue(async () => { renderState(await api.patch({hotkeys: {[action]: value}})); });
      } catch (err) { showError(err); button.textContent = cfg.hotkeys[action]; }
      finally { button.disabled = false; }
    });
    row.append(label, button);
    section.appendChild(row);
  }
  return section;
}

function bindAction(selector, work) {
  const button = $(selector);
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await flushPatch();
      await enqueue(work);
    } catch (err) { showError(err); }
    finally { button.disabled = false; }
  });
}

function isEditingConfig() {
  return patchFlight !== null || Object.keys(pendingPatch).length > 0 ||
    (document.hasFocus() && /^(INPUT|SELECT)$/.test(document.activeElement?.tagName || ""));
}

async function boot() {
  try {
    api = window.pywebview.api;
    monitors = await api.monitors();
    hotkeyLabels = await api.hotkey_options();
    renderState(await api.state());
    $("#startup").checked = await api.startup();
    $("#startup").addEventListener("change", async (event) => {
      const input = event.target;
      try { input.checked = await api.startup(input.checked); }
      catch (err) { input.checked = !input.checked; showError(err); }
    });
    $("#start-hidden").addEventListener("change", (event) =>
      setValue(null, "start_hidden", event.target.checked));
    $("#colour-input").addEventListener("input", (event) =>
      applyColour(event.target.value.toUpperCase()));
    document.querySelectorAll(".btn-preset").forEach((btn) => {
      bindAction(`[data-preset="${btn.dataset.preset}"]`, async () => {
        renderState(await api.preset(btn.dataset.preset));
        btn.classList.add("active");
      });
    });
    bindAction("#btn-reset", async () => {
      renderState(await api.reset());
      notify("已恢复默认设置");
    });
    bindAction("#btn-start", async () => {
      const state = await api.start_overlay();
      setStatus(state.overlay_alive);
      if (!state.overlay_alive) throw new Error("叠加层启动失败，请检查日志后重试");
    });
    bindAction("#btn-stop", async () => {
      const state = await api.stop_overlay();
      setStatus(state.overlay_alive);
      if (state.overlay_alive) throw new Error("叠加层尚未停止，请稍后重试");
    });
    bindAction("#btn-toggle", async () => setStatus((await api.toggle_overlay()).overlay_alive));
    bindAction("#btn-import", async () => {
      const state = await api.import_config();
      if (state) { renderState(state); notify("配置已导入"); }
    });
    bindAction("#btn-export", async () => {
      const path = await api.export_config();
      if (path) notify("配置已导出");
    });
    // Refresh changes made using the tray or global shortcuts without moving a slider under the cursor.
    setInterval(async () => {
      if (isEditingConfig()) return;
      try {
        await enqueue(async () => {
          if (isEditingConfig()) return;
          const revision = editRevision;
          const requestedConfig = JSON.stringify(cfg);
          const state = await api.state();
          // Input may start while the queued request is waiting or in flight.
          if (isEditingConfig() || revision !== editRevision ||
              requestedConfig !== JSON.stringify(cfg)) return;
          setStatus(state.overlay_alive);
          if (JSON.stringify(state.config) !== requestedConfig) renderState(state);
        });
      } catch (err) { showError(err); }
    }, 2000);
    window.__horizonReady = true;
  } catch (err) { showError(err); }
}

window.addEventListener("unhandledrejection", (event) => showError(event.reason));
window.addEventListener("pywebviewready", boot);
