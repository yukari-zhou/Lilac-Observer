(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const dialog = byId("settings-dialog");
  const form = byId("settings-form");
  const trigger = byId("model-settings");
  const providers = form.elements.provider;
  const apiUrl = byId("api-url");
  const apiModel = byId("api-model");
  const apiKey = byId("api-key");
  const clearKey = byId("clear-key");
  const feedback = byId("settings-feedback");
  let settings, busy = false, generation = 0;

  function status(text, failed = false) {
    feedback.textContent = text;
    feedback.classList.toggle("error", failed);
  }
  function keyHint() {
    const changed = apiUrl.value.trim().replace(/\/$/, "") !== (settings?.base_url || "").replace(/\/$/, "");
    apiKey.placeholder = settings?.has_api_key && !changed ? "留空以保留现有密钥" : "输入 API 密钥";
    byId("key-state").textContent = changed && settings?.has_api_key
      ? "已更换地址，如需认证请填写新服务的密钥"
      : ({local: "本机已保存密钥", environment: "使用环境变量中的密钥", none: "当前未配置密钥"})[settings?.key_source] || "";
  }
  function sync() {
    const provider = providers.value;
    const api = provider === "api";
    byId("provider-fields").disabled = busy || !settings;
    byId("codex-fields").hidden = provider !== "codex";
    byId("api-fields").hidden = !api;
    byId("off-explanation").hidden = provider !== "off";
    apiUrl.required = api;
    apiModel.required = api;
    apiUrl.disabled = apiModel.disabled = !api || busy;
    apiKey.disabled = !api || clearKey.checked || busy;
    byId("codex-model").disabled = provider !== "codex" || busy;
    const localKey = settings?.key_source === "local";
    byId("clear-key-label").hidden = !localKey;
    clearKey.disabled = !localKey || busy;
    byId("settings-close").disabled = byId("settings-cancel").disabled = busy;
    byId("settings-save").disabled = busy || !settings;
    byId("settings-retry").hidden = !!settings || busy;
    const modeNote = byId("offline-note");
    modeNote.hidden = !settings?.offline && !settings?.disabled_by_env;
    modeNote.textContent = settings?.offline
      ? "当前启用离线模式。恢复联网模式后，所选模型可参与复核。"
      : "当前服务通过环境变量关闭了 AI 复核。调整环境变量并重启服务后可启用复核。";
  }
  async function request(options = {}) {
    const response = await fetch("/api/settings", {
      cache: "no-store", signal: AbortSignal.timeout(12000), ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `设置请求失败（HTTP ${response.status}）`);
    if (!["codex", "api", "off"].includes(data.provider)) throw new Error("服务返回的模型设置无效");
    return data;
  }
  function populate(data) {
    settings = data;
    providers.value = data.provider;
    byId("codex-model").value = data.codex_model || "";
    apiUrl.value = data.base_url || "";
    apiModel.value = data.api_model || "";
    apiKey.value = "";
    keyHint();
    byId("codex-state").textContent = data.codex_available
      ? "已找到本机 Codex CLI，将使用其登录状态。"
      : "未找到本机 Codex CLI，选择此方式前请安装并登录 Codex。";
    clearKey.checked = false;
  }
  async function load() {
    const token = ++generation;
    busy = true;
    settings = null;
    form.reset();
    status("正在读取本机设置…");
    sync();
    // Allow dismissing a pending read. Only a save must finish before closing.
    byId("settings-close").disabled = byId("settings-cancel").disabled = false;
    try {
      const data = await request();
      if (token !== generation) return;
      populate(data);
      status(data.warning || "", !!data.warning);
    } catch (error) {
      if (token === generation) status(error.message, true);
    } finally {
      if (token === generation) {
        busy = false;
        sync();
      }
    }
  }
  apiUrl.addEventListener("input", keyHint);
  form.addEventListener("change", (event) => {
    if (event.target === clearKey && clearKey.checked) apiKey.value = "";
    if (event.target.name === "provider" || event.target === clearKey) {
      status("");
      sync();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!settings || busy) return;
    const provider = providers.value;
    const payload = { provider };
    if (provider === "codex") payload.codex_model = byId("codex-model").value.trim();
    if (provider === "api") {
      payload.api_model = apiModel.value.trim();
      payload.base_url = apiUrl.value.trim();
      if (!payload.api_model) {
        status("请填写服务端提供的模型 ID。", true);
        apiModel.focus();
        return;
      }
      if (apiKey.value.trim()) payload.api_key = apiKey.value.trim();
      else if (clearKey.checked) payload.clear_api_key = true;
    }
    busy = true;
    status("正在保存…");
    sync();
    try {
      await request({method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      busy = false;
      dialog.close();
      window.dispatchEvent(new Event("model-settings-changed"));
    } catch (error) {
      busy = false;
      status(error.message, true);
      sync();
    }
  });
  trigger.addEventListener("click", () => {
    dialog.showModal();
    load();
  });
  byId("settings-retry").addEventListener("click", load);
  for (const id of ["settings-cancel", "settings-close"]) {
    byId(id).addEventListener("click", () => dialog.close());
  }
  dialog.addEventListener("cancel", (event) => {
    if (busy && settings) event.preventDefault();
  });
  dialog.addEventListener("close", () => {
    generation++;
    settings = null;
    busy = false;
    apiKey.value = "";
    form.reset();
    trigger.focus();
  });
})();
