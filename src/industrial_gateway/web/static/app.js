const state = { devices: [], selectedDevice: null, ws: null };

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) throw await response.json().catch(() => ({ message: response.statusText }));
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch]));
}

function showConsole(show) {
  document.getElementById("loginView").classList.toggle("hidden", show);
  document.getElementById("consoleView").classList.toggle("hidden", !show);
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
  state.devices = await api("/api/devices");
  state.selectedDevice = state.devices[0] || null;
  renderDevices();
  await loadPlugin();
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
  renderDevices();
}

function renderDeviceForm(device) {
  state.selectedDevice = device;
  const form = document.getElementById("deviceForm");
  const data = device || { name: "", device_group: "", driver_type: "modbus_tcp", enabled: true, poll_interval_ms: 1000, connection: {} };
  form.innerHTML = `
    <h2>Device</h2>
    <label>Group <input name="device_group" value="${escapeHtml(data.device_group || "")}"></label>
    <label>Name <input name="name" value="${escapeHtml(data.name || "")}" required></label>
    <label>Driver <select name="driver_type"><option>modbus_tcp</option><option>modbus_serial</option><option>opcua</option></select></label>
    <label>Enabled <input name="enabled" type="checkbox" ${data.enabled ? "checked" : ""}></label>
    <label>Poll ms <input name="poll_interval_ms" type="number" min="100" value="${data.poll_interval_ms || 1000}"></label>
    <label>Connection JSON <input name="connection" value='${escapeHtml(JSON.stringify(data.connection || {}))}'></label>
    <button type="submit">Save device</button>
  `;
  form.elements.driver_type.value = data.driver_type || "modbus_tcp";
  form.onsubmit = saveDevice;
  renderTagForm();
}

async function saveDevice(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    device_group: form.elements.device_group.value,
    name: form.elements.name.value,
    driver_type: form.elements.driver_type.value,
    enabled: form.elements.enabled.checked,
    poll_interval_ms: Number(form.elements.poll_interval_ms.value),
    connection: JSON.parse(form.elements.connection.value || "{}")
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
  form.innerHTML = `
    <h2>New Tag</h2>
    <label>Name <input name="name" required></label>
    <label>NodeId <input name="node_id"></label>
    <label>Address <input name="address" type="number" value="0"></label>
    <label>Function <select name="function"><option>holding_register</option><option>input_register</option><option>coil</option><option>discrete_input</option><option>opcua_node</option></select></label>
    <label>Data type <select name="data_type"><option>auto</option><option>bool</option><option>int16</option><option>uint16</option><option>int32</option><option>uint32</option><option>float32</option><option>float64</option><option>string</option></select></label>
    <label>Scale <input name="scale" type="number" value="1"></label>
    <button type="submit">Add tag</button>
  `;
  form.onsubmit = saveTag;
}

async function loadTags() {
  const tbody = document.getElementById("tagList");
  if (!state.selectedDevice) {
    tbody.innerHTML = "";
    return;
  }
  const tags = await api(`/api/devices/${state.selectedDevice.id}/tags`);
  tbody.innerHTML = tags.map(tag => `<tr><td>${escapeHtml(tag.name)}</td><td>${escapeHtml(tag.function)}</td><td>${escapeHtml(tag.data_type)}</td></tr>`).join("");
}

async function saveTag(event) {
  event.preventDefault();
  if (!state.selectedDevice) return;
  const form = event.currentTarget;
  await api(`/api/devices/${state.selectedDevice.id}/tags`, {
    method: "POST",
    body: JSON.stringify({
      name: form.elements.name.value,
      node_id: form.elements.node_id.value,
      address: Number(form.elements.address.value),
      function: form.elements.function.value,
      data_type: form.elements.data_type.value,
      scale: Number(form.elements.scale.value),
      enabled: true
    })
  });
  form.reset();
  await loadTags();
}

async function loadPlugin() {
  const plugin = await api("/api/plugins/mqtt");
  const form = document.getElementById("pluginForm");
  form.innerHTML = `
    <label>Enabled <input name="enabled" type="checkbox" ${plugin.enabled ? "checked" : ""}></label>
    <label>Config JSON <input name="config" value='${escapeHtml(JSON.stringify(plugin.config))}'></label>
    <button type="submit">Save plugin</button>
  `;
  form.onsubmit = async event => {
    event.preventDefault();
    await api("/api/plugins/mqtt", {
      method: "PUT",
      body: JSON.stringify({ enabled: form.elements.enabled.checked, config: JSON.parse(form.elements.config.value || "{}") })
    });
  };
}

async function loadRuntime() {
  renderRuntime(await api("/api/runtime/status"));
}

function renderRuntime(snapshot) {
  document.getElementById("runtimeBadge").textContent = snapshot.running ? "Running" : "Stopped";
  document.getElementById("runtimeTags").innerHTML = snapshot.runtime_tags.map(row =>
    `<tr><td>${escapeHtml(row.device)}</td><td>${escapeHtml(row.tag)}</td><td>${escapeHtml(row.mode)}</td><td>${escapeHtml(row.timestamp || "")}</td><td>${escapeHtml(row.error || row.quality)}</td></tr>`
  ).join("");
  document.getElementById("logs").textContent = (snapshot.logs || []).join("\n");
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
document.getElementById("newDevice").onclick = () => renderDeviceForm(null);
document.getElementById("startRuntime").onclick = async () => renderRuntime(await api("/api/runtime/start", { method: "POST", body: JSON.stringify({ health_interval_s: Number(document.getElementById("healthInterval").value) }) }));
document.getElementById("stopRuntime").onclick = async () => renderRuntime(await api("/api/runtime/stop", { method: "POST" }));
document.querySelectorAll(".tabs button").forEach(button => button.onclick = () => {
  document.querySelectorAll(".tabs button").forEach(item => item.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(item => item.classList.add("hidden"));
  button.classList.add("active");
  document.getElementById(`${button.dataset.tab}Tab`).classList.remove("hidden");
});
api("/api/session").then(() => loadAll().then(() => showConsole(true))).catch(() => showConsole(false));
