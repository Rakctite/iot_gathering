const state = {
  devices: [],
  selectedDevice: null,
  selectedTag: null,
  tagRows: [],
  tagGroupPage: 0,
  tagListPage: 0,
  tagPageSize: 12,
  driverSchema: {},
  pluginSchema: {},
  selectedPlugin: "mqtt",
  pluginRoutes: [],
  selectedPluginRoute: null,
  selectedRoutePlugin: "mqtt",
  runtimeSnapshot: { running: false, runtime_tags: [], logs: [] },
  runtimeTagPage: 0,
  runtimePageSize: 12,
  ws: null
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) throw await response.json().catch(() => ({ message: response.statusText }));
  return response.json();
}

async function uploadCsv(path, file) {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "text/csv" },
    body: await file.text()
  });
  if (!response.ok) throw await response.json().catch(() => ({ message: response.statusText }));
  return response.json();
}

function downloadCsv(path) {
  window.location.href = path;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch]));
}

function showConsole(show) {
  document.getElementById("loginView").classList.toggle("hidden", show);
  document.getElementById("consoleView").classList.toggle("hidden", !show);
}

function valueForField(field, values = {}) {
  return values[field.key] ?? field.default ?? "";
}

function renderField(field, values = {}, prefix = "") {
  const name = `${prefix}${field.key}`;
  const value = valueForField(field, values);
  if (field.kind === "choice") {
    const options = (field.choices || []).map(choice =>
      `<option value="${escapeHtml(choice)}" ${choice === value ? "selected" : ""}>${escapeHtml(choice)}</option>`
    ).join("");
    return `<label>${escapeHtml(field.label)} <select name="${escapeHtml(name)}">${options}</select></label>`;
  }
  if (field.kind === "bool") {
    return `<label class="checkbox-row"><input name="${escapeHtml(name)}" type="checkbox" ${value ? "checked" : ""}> ${escapeHtml(field.label)}</label>`;
  }
  const type = field.kind === "int" || field.kind === "float" ? "number" : field.kind === "password" ? "password" : "text";
  const step = field.kind === "float" ? ` step="any"` : "";
  const min = field.minimum !== null && field.minimum !== undefined ? ` min="${field.minimum}"` : "";
  const max = field.maximum !== null && field.maximum !== undefined ? ` max="${field.maximum}"` : "";
  return `<label>${escapeHtml(field.label)} <input name="${escapeHtml(name)}" type="${type}" value="${escapeHtml(value)}"${step}${min}${max}></label>`;
}

function readFieldValue(form, field, prefix = "") {
  const control = form.elements[`${prefix}${field.key}`];
  if (!control) return field.default;
  if (field.kind === "bool") return control.checked;
  if (field.kind === "int") return Number.parseInt(control.value || field.default || 0, 10);
  if (field.kind === "float") return Number.parseFloat(control.value || field.default || 0);
  return control.value;
}

function readFields(form, fields, prefix = "") {
  return Object.fromEntries(fields.map(field => [field.key, readFieldValue(form, field, prefix)]));
}

async function login(event) {
  event.preventDefault();
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value
      })
    });
    document.getElementById("loginError").textContent = "";
    await loadAll();
    showConsole(true);
  } catch (error) {
    document.getElementById("loginError").textContent = error.message || "Login failed";
  }
}

async function loadAll() {
  state.driverSchema = await api("/api/schema/drivers");
  state.pluginSchema = await api("/api/schema/plugins");
  state.devices = await api("/api/devices");
  state.selectedDevice = state.devices[0] || null;
  renderDevices();
  await loadPlugin();
  await loadPluginRoutes();
  await loadRuntime();
  connectRuntimeEvents();
}

function renderDevices() {
  const list = document.getElementById("deviceList");
  list.innerHTML = "";
  state.devices.forEach(device => {
    const item = document.createElement("li");
    item.textContent = `${device.device_group ? device.device_group + " / " : ""}${device.name}`;
    item.className = state.selectedDevice && state.selectedDevice.id === device.id ? "active" : "";
    item.onclick = () => selectDevice(device);
    list.appendChild(item);
  });
  renderDeviceForm(state.selectedDevice);
  loadTags();
}

function selectDevice(device) {
  state.selectedDevice = device;
  state.selectedTag = null;
  state.tagGroupPage = 0;
  state.tagListPage = 0;
  renderDevices();
}

function renderDeviceForm(device) {
  state.selectedDevice = device;
  const form = document.getElementById("deviceForm");
  const data = device || { name: "", device_group: "", driver_type: "modbus_tcp", enabled: true, poll_interval_ms: 1000, connection: {} };
  const driverTypes = Object.keys(state.driverSchema);
  const driverOptions = driverTypes.map(driver =>
    `<option value="${escapeHtml(driver)}" ${driver === data.driver_type ? "selected" : ""}>${escapeHtml(driver)}</option>`
  ).join("");
  const fields = state.driverSchema[data.driver_type]?.connection_fields || [];
  form.innerHTML = `
    <h2>Device</h2>
    <label>Group <input name="device_group" value="${escapeHtml(data.device_group || "")}"></label>
    <label>Name <input name="name" value="${escapeHtml(data.name || "")}" required></label>
    <label>Driver <select name="driver_type">${driverOptions}</select></label>
    <label class="checkbox-row"><input name="enabled" type="checkbox" ${data.enabled ? "checked" : ""}> Enabled</label>
    <label>Poll ms <input name="poll_interval_ms" type="number" min="100" value="${data.poll_interval_ms || 1000}"></label>
    <div id="connectionFields">${fields.map(field => renderField(field, data.connection, "connection_")).join("")}</div>
    <button type="submit">Save device</button>
    ${data.id ? `<button id="deleteDevice" type="button">Delete device</button>` : ""}
  `;
  form.elements.driver_type.onchange = () => {
    const next = { ...data, driver_type: form.elements.driver_type.value, connection: {} };
    renderDeviceForm(next);
  };
  form.onsubmit = saveDevice;
  if (data.id) {
    document.getElementById("deleteDevice").onclick = deleteDevice;
  }
  renderTagForm();
}

async function deleteDevice() {
  if (!state.selectedDevice || !state.selectedDevice.id) return;
  await api(`/api/devices/${state.selectedDevice.id}`, { method: "DELETE" });
  state.devices = await api("/api/devices");
  state.selectedDevice = state.devices[0] || null;
  state.selectedTag = null;
  renderDevices();
  await loadPluginRoutes();
}

async function saveDevice(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const driverType = form.elements.driver_type.value;
  const connectionFields = state.driverSchema[driverType]?.connection_fields || [];
  const payload = {
    device_group: form.elements.device_group.value,
    name: form.elements.name.value,
    driver_type: driverType,
    enabled: form.elements.enabled.checked,
    poll_interval_ms: Number(form.elements.poll_interval_ms.value),
    connection: readFields(form, connectionFields, "connection_")
  };
  if (state.selectedDevice && state.selectedDevice.id) {
    await api(`/api/devices/${state.selectedDevice.id}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/api/devices", { method: "POST", body: JSON.stringify(payload) });
  }
  state.devices = await api("/api/devices");
  state.selectedDevice = state.devices.find(device => device.name === payload.name) || state.devices[0] || null;
  renderDevices();
}

function renderTagForm() {
  const form = document.getElementById("tagForm");
  const driverType = state.selectedDevice?.driver_type || "modbus_tcp";
  const schema = state.driverSchema[driverType] || { tag_functions: [], tag_types: [] };
  const data = state.selectedTag || { tag_group: "", name: "", node_id: "", address: 0, function: schema.tag_functions[0] || "", data_type: schema.tag_types[0] || "", scale: 1, enabled: true };
  const functionOptions = schema.tag_functions.map(item => `<option value="${escapeHtml(item)}" ${item === data.function ? "selected" : ""}>${escapeHtml(item)}</option>`).join("");
  const typeOptions = schema.tag_types.map(item => `<option value="${escapeHtml(item)}" ${item === data.data_type ? "selected" : ""}>${escapeHtml(item)}</option>`).join("");
  form.innerHTML = `
    <h2>${data.id ? "Tag" : "New Tag"}</h2>
    <label>Group <input name="tag_group" value="${escapeHtml(data.tag_group || "")}"></label>
    <label>Name <input name="name" value="${escapeHtml(data.name || "")}" required></label>
    <label>NodeId <input name="node_id" value="${escapeHtml(data.node_id || "")}"></label>
    <label>Address <input name="address" type="number" value="${data.address || 0}"></label>
    <label>Function <select name="function">${functionOptions}</select></label>
    <label>Data type <select name="data_type">${typeOptions}</select></label>
    <label>Scale <input name="scale" type="number" step="any" value="${data.scale || 1}"></label>
    <label class="checkbox-row"><input name="enabled" type="checkbox" ${data.enabled ? "checked" : ""}> Enabled</label>
    <button type="submit">${data.id ? "Save tag" : "Add tag"}</button>
    <button id="newTag" type="button">New tag</button>
    ${data.id ? `<button id="deleteTag" type="button">Delete tag</button>` : ""}
  `;
  form.onsubmit = saveTag;
  document.getElementById("newTag").onclick = () => {
    state.selectedTag = null;
    renderTags();
    renderTagForm();
  };
  if (data.id) {
    document.getElementById("deleteTag").onclick = deleteTag;
  }
}

async function loadTags() {
  const tbody = document.getElementById("tagList");
  if (!state.selectedDevice) {
    state.tagRows = [];
    tbody.innerHTML = "";
    renderTagPageLabels({ groups: [], selectedGroup: "", pageCount: 1, totalRows: 0 });
    return;
  }
  state.tagRows = await api(`/api/devices/${state.selectedDevice.id}/tags`);
  if (state.selectedTag) {
    state.selectedTag = state.tagRows.find(tag => tag.id === state.selectedTag.id) || null;
  }
  renderTags();
}

function renderTags() {
  const page = tagPageRows(state.tagRows || []);
  document.getElementById("tagList").innerHTML = page.rows.map(tag =>
    `<tr class="${state.selectedTag && state.selectedTag.id === tag.id ? "active" : ""}" data-tag-id="${tag.id}"><td>${escapeHtml(tag.tag_group || "")}</td><td>${escapeHtml(tag.name)}</td><td>${escapeHtml(tag.function)}</td><td>${escapeHtml(tag.data_type)}</td></tr>`
  ).join("");
  document.querySelectorAll("#tagList tr").forEach(row => row.onclick = () => selectTag(Number(row.dataset.tagId)));
  renderTagPageLabels(page);
}

function selectTag(tagId) {
  state.selectedTag = state.tagRows.find(tag => tag.id === tagId) || null;
  renderTags();
  renderTagForm();
}

function tagPageRows(rows) {
  const groups = uniqueValues(rows.map(row => row.tag_group || "default"));
  state.tagGroupPage = clampPage(state.tagGroupPage, groups.length);
  const selectedGroup = groups[state.tagGroupPage] || "";
  const groupRows = selectedGroup
    ? rows.filter(row => (row.tag_group || "default") === selectedGroup)
    : rows;
  const pageCount = Math.max(1, Math.ceil(groupRows.length / state.tagPageSize));
  state.tagListPage = clampPage(state.tagListPage, pageCount);
  const start = state.tagListPage * state.tagPageSize;
  return {
    rows: groupRows.slice(start, start + state.tagPageSize),
    groups,
    selectedGroup,
    pageCount,
    totalRows: groupRows.length
  };
}

function renderTagPageLabels(page) {
  document.getElementById("tagGroupPageLabel").textContent = page.groups.length
    ? `${state.tagGroupPage + 1}/${page.groups.length} ${shortLabel(page.selectedGroup)}`
    : "0/0";
  document.getElementById("tagListPageLabel").textContent = `${state.tagListPage + 1}/${page.pageCount} (${page.totalRows})`;
}

function turnTagPage(kind, delta) {
  if (kind === "group") {
    state.tagGroupPage += delta;
    state.tagListPage = 0;
  } else {
    state.tagListPage += delta;
  }
  renderTags();
}

async function saveTag(event) {
  event.preventDefault();
  if (!state.selectedDevice) return;
  const form = event.currentTarget;
  const payload = {
    tag_group: form.elements.tag_group.value,
    name: form.elements.name.value,
    node_id: form.elements.node_id.value,
    address: Number(form.elements.address.value),
    function: form.elements.function.value,
    data_type: form.elements.data_type.value,
    scale: Number(form.elements.scale.value),
    enabled: form.elements.enabled.checked
  };
  if (state.selectedTag && state.selectedTag.id) {
    await api(`/api/tags/${state.selectedTag.id}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  } else {
    await api(`/api/devices/${state.selectedDevice.id}/tags`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }
  state.selectedTag = null;
  await loadTags();
}

async function deleteTag() {
  if (!state.selectedTag || !state.selectedTag.id) return;
  await api(`/api/tags/${state.selectedTag.id}`, { method: "DELETE" });
  state.selectedTag = null;
  await loadTags();
}

async function importDevicesCsv(file) {
  if (!file) return;
  await uploadCsv("/api/devices/import", file);
  state.devices = await api("/api/devices");
  state.selectedDevice = state.devices[0] || null;
  renderDevices();
}

async function importTagsCsv(file) {
  if (!file || !state.selectedDevice) return;
  await uploadCsv(`/api/devices/${state.selectedDevice.id}/tags/import`, file);
  await loadTags();
}

async function loadPlugin() {
  const plugin = await api(`/api/plugins/${state.selectedPlugin}`);
  const form = document.getElementById("pluginForm");
  const pluginOptions = Object.keys(state.pluginSchema).map(pluginType =>
    `<option value="${escapeHtml(pluginType)}" ${pluginType === state.selectedPlugin ? "selected" : ""}>${escapeHtml(pluginType)}</option>`
  ).join("");
  const fields = state.pluginSchema[state.selectedPlugin]?.fields || [];
  form.innerHTML = `
    <label>Plugin <select name="sink_type">${pluginOptions}</select></label>
    <label class="checkbox-row"><input name="enabled" type="checkbox" ${plugin.enabled ? "checked" : ""}> Enabled</label>
    <div id="pluginFields">${fields.map(field => renderField(field, plugin.config, "plugin_")).join("")}</div>
    <button type="submit">Save plugin</button>
  `;
  form.elements.sink_type.onchange = async () => {
    state.selectedPlugin = form.elements.sink_type.value;
    state.selectedPluginRoute = null;
    await loadPlugin();
  };
  form.onsubmit = async event => {
    event.preventDefault();
    await api(`/api/plugins/${state.selectedPlugin}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: form.elements.enabled.checked, config: readFields(form, fields, "plugin_") })
    });
    renderPluginRouteVisibility();
  };
  renderPluginRouteVisibility();
}

async function loadRuntime() {
  renderRuntime(await api("/api/runtime/status"));
}

function renderRuntime(snapshot) {
  state.runtimeSnapshot = snapshot;
  document.getElementById("runtimeBadge").textContent = snapshot.running ? "Running" : "Stopped";
  const runtimeRows = runtimePageRows(snapshot.runtime_tags || []);
  document.getElementById("runtimeTags").innerHTML = runtimeRows.rows.map(row =>
    `<tr><td>${escapeHtml(row.device)}</td><td>${escapeHtml(row.tag_group || "")}</td><td>${escapeHtml(row.tag)}</td><td>${escapeHtml(row.mode)}</td><td>${escapeHtml(row.timestamp || "")}</td><td>${escapeHtml(row.error || row.quality)}</td></tr>`
  ).join("");
  document.getElementById("logs").textContent = (snapshot.logs || []).join("\n");
  renderRuntimePageLabels(runtimeRows);
}

function runtimePageRows(rows) {
  const sortedRows = [...rows].sort((left, right) =>
    `${left.device || ""}\u0000${left.tag_group || ""}\u0000${left.tag || ""}`.localeCompare(
      `${right.device || ""}\u0000${right.tag_group || ""}\u0000${right.tag || ""}`
    )
  );
  const pageCount = Math.max(1, Math.ceil(sortedRows.length / state.runtimePageSize));
  state.runtimeTagPage = clampPage(state.runtimeTagPage, pageCount);
  const start = state.runtimeTagPage * state.runtimePageSize;
  return {
    rows: sortedRows.slice(start, start + state.runtimePageSize),
    pageCount,
    totalRows: sortedRows.length
  };
}

async function loadPluginRoutes() {
  state.pluginRoutes = await api("/api/plugin-routes");
  renderPluginRouteForm(state.selectedPluginRoute);
  renderPluginRoutes();
  renderPluginRouteVisibility();
}

function renderPluginRouteForm(route) {
  const form = document.getElementById("pluginRouteForm");
  const data = route || { device_id: state.selectedDevice?.id || "", tag_group: "", sink_type: "mqtt", enabled: true, config: {} };
  state.selectedRoutePlugin = "mqtt";
  const deviceOptions = [
    `<option value="">All devices</option>`,
    ...state.devices.map(device =>
      `<option value="${device.id}" ${Number(data.device_id) === device.id ? "selected" : ""}>${escapeHtml(device.name)}</option>`
    )
  ].join("");
  form.innerHTML = `
    <h3>${data.id ? "Route" : "New Route"}</h3>
    <label>Device <select name="device_id">${deviceOptions}</select></label>
    <label>Tag group <input name="tag_group" value="${escapeHtml(data.tag_group || "")}" placeholder="empty = all groups"></label>
    <label>Topic <input name="topic" value="${escapeHtml(data.config?.topic || "")}" placeholder="empty = auto topic"></label>
    <label class="checkbox-row"><input name="enabled" type="checkbox" ${data.enabled ? "checked" : ""}> Enabled</label>
    <button type="submit">${data.id ? "Save route" : "Add route"}</button>
    <button id="newPluginRoute" type="button">New route</button>
    ${data.id ? `<button id="deletePluginRoute" type="button">Delete route</button>` : ""}
  `;
  form.onsubmit = savePluginRoute;
  document.getElementById("newPluginRoute").onclick = () => {
    state.selectedPluginRoute = null;
    renderPluginRoutes();
    renderPluginRouteForm(null);
  };
  if (data.id) document.getElementById("deletePluginRoute").onclick = deletePluginRoute;
}

function renderPluginRoutes() {
  document.getElementById("pluginRouteList").innerHTML = state.pluginRoutes.filter(route => route.sink_type === "mqtt").map(route =>
    `<tr class="${state.selectedPluginRoute && state.selectedPluginRoute.id === route.id ? "active" : ""}" data-route-id="${route.id}"><td>${escapeHtml(route.device_name || "All devices")}</td><td>${escapeHtml(route.tag_group || "All groups")}</td><td>${escapeHtml(route.sink_type)}</td><td>${route.enabled ? "Yes" : "No"}</td></tr>`
  ).join("");
  document.querySelectorAll("#pluginRouteList tr").forEach(row => row.onclick = () => selectPluginRoute(Number(row.dataset.routeId)));
}

function renderPluginRouteVisibility() {
  const visible = state.selectedPlugin === "mqtt";
  document.getElementById("pluginRouteEditor").classList.toggle("hidden", !visible);
  document.getElementById("pluginRouteListPanel").classList.toggle("hidden", !visible);
}

function selectPluginRoute(routeId) {
  state.selectedPluginRoute = state.pluginRoutes.find(route => route.id === routeId) || null;
  renderPluginRoutes();
  renderPluginRouteForm(state.selectedPluginRoute);
}

async function savePluginRoute(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    device_id: form.elements.device_id.value || null,
    tag_group: form.elements.tag_group.value,
    sink_type: "mqtt",
    enabled: form.elements.enabled.checked,
    config: { topic: form.elements.topic.value }
  };
  if (state.selectedPluginRoute && state.selectedPluginRoute.id) {
    await api(`/api/plugin-routes/${state.selectedPluginRoute.id}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/api/plugin-routes", { method: "POST", body: JSON.stringify(payload) });
  }
  state.selectedPluginRoute = null;
  await loadPluginRoutes();
}

async function deletePluginRoute() {
  if (!state.selectedPluginRoute || !state.selectedPluginRoute.id) return;
  await api(`/api/plugin-routes/${state.selectedPluginRoute.id}`, { method: "DELETE" });
  state.selectedPluginRoute = null;
  await loadPluginRoutes();
}

function renderRuntimePageLabels(page) {
  document.getElementById("tagPageLabel").textContent = `${state.runtimeTagPage + 1}/${page.pageCount} (${page.totalRows})`;
}

function shortLabel(value, max = 18) {
  const text = String(value || "");
  const limit = Math.max(0, max - 3);
  return text.length > max ? `${text.slice(0, limit)}...` : text;
}

function uniqueValues(values) {
  return [...new Set(values.filter(value => value !== ""))];
}

function clampPage(index, count) {
  if (count <= 0) return 0;
  return Math.min(Math.max(index, 0), count - 1);
}

function turnRuntimePage(kind, delta) {
  state.runtimeTagPage += delta;
  renderRuntime(state.runtimeSnapshot);
}

function connectRuntimeEvents() {
  if (state.ws) state.ws.close();
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${scheme}://${location.host}/api/runtime/events`);
  state.ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === "snapshot") renderRuntime(message.payload);
    if (message.type === "log" || message.type === "tag_update" || message.type === "server_status") loadRuntime();
  };
}

document.getElementById("loginForm").addEventListener("submit", login);
document.getElementById("logoutButton").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); showConsole(false); };
document.getElementById("newDevice").onclick = () => {
  state.selectedDevice = null;
  state.selectedTag = null;
  state.tagRows = [];
  renderDevices();
};
document.getElementById("importDevices").onclick = () => document.getElementById("deviceCsvFile").click();
document.getElementById("exportDevices").onclick = () => downloadCsv("/api/devices.csv");
document.getElementById("deviceCsvFile").onchange = async event => {
  try {
    await importDevicesCsv(event.target.files[0]);
    event.target.value = "";
  } catch (error) {
    alert(error.message || "Device CSV import failed");
  }
};
document.getElementById("importTags").onclick = () => document.getElementById("tagCsvFile").click();
document.getElementById("exportTags").onclick = () => {
  if (!state.selectedDevice) return;
  downloadCsv(`/api/devices/${state.selectedDevice.id}/tags.csv`);
};
document.getElementById("prevTagGroupPage").onclick = () => turnTagPage("group", -1);
document.getElementById("nextTagGroupPage").onclick = () => turnTagPage("group", 1);
document.getElementById("prevTagListPage").onclick = () => turnTagPage("tag", -1);
document.getElementById("nextTagListPage").onclick = () => turnTagPage("tag", 1);
document.getElementById("tagCsvFile").onchange = async event => {
  try {
    await importTagsCsv(event.target.files[0]);
    event.target.value = "";
  } catch (error) {
    alert(error.message || "Tag CSV import failed");
  }
};
document.getElementById("startRuntime").onclick = async () => renderRuntime(await api("/api/runtime/start", { method: "POST", body: JSON.stringify({ health_interval_s: Number(document.getElementById("healthInterval").value) }) }));
document.getElementById("stopRuntime").onclick = async () => renderRuntime(await api("/api/runtime/stop", { method: "POST" }));
document.getElementById("prevTagPage").onclick = () => turnRuntimePage("tag", -1);
document.getElementById("nextTagPage").onclick = () => turnRuntimePage("tag", 1);
document.querySelectorAll(".tabs button").forEach(button => button.onclick = () => {
  document.querySelectorAll(".tabs button").forEach(item => item.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(item => item.classList.add("hidden"));
  button.classList.add("active");
  document.getElementById(`${button.dataset.tab}Tab`).classList.remove("hidden");
});
api("/api/session").then(() => loadAll().then(() => showConsole(true))).catch(() => showConsole(false));
