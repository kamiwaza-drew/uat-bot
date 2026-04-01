(() => {
  const STORAGE_KEY = "uat_bot.ui.v2";

  const profiles = {
    smoke: {
      concurrent_users: 3,
      role_distribution: { admin: 1, editor: 1, viewer: 1 },
      browser_distribution: { chromium: 1, firefox: 1, webkit: 1 },
      os_emulation: ["win-chrome", "mac-firefox", "mac-safari"],
      scenarios: ["login"],
      scenario_weights: { login: 1 },
      duration_seconds: 120,
      ramp_up_seconds: 10,
      vision_enabled: false,
      exploratory_pct: 0,
    },
    load: {
      concurrent_users: 20,
      role_distribution: { admin: 2, editor: 8, viewer: 10 },
      browser_distribution: { chromium: 10, firefox: 6, webkit: 4 },
      os_emulation: ["win-chrome", "mac-safari", "mac-firefox", "linux-chrome", "iphone-15", "pixel-7"],
      scenarios: ["login"],
      scenario_weights: { login: 1 },
      duration_seconds: 600,
      ramp_up_seconds: 60,
      vision_enabled: true,
      exploratory_pct: 0.1,
    },
    soak: {
      concurrent_users: 5,
      role_distribution: { admin: 1, editor: 2, viewer: 2 },
      browser_distribution: { chromium: 3, firefox: 1, webkit: 1 },
      os_emulation: ["win-chrome", "mac-firefox", "mac-safari"],
      scenarios: ["login"],
      scenario_weights: { login: 1 },
      duration_seconds: 3600,
      ramp_up_seconds: 30,
      vision_enabled: false,
      exploratory_pct: 0,
    },
  };

  const SCENARIO_PATHS = {
    model_deploy: { scenarios: ["model_browse", "model_deploy"] },
    app_tool_deploy: { scenarios: ["app_deploy", "app_garden", "vectordb"] },
    user_admin: { scenarios: ["cluster_admin", "rbac_boundary"] },
  };

  const PATH_INPUTS = {
    model_deploy: "path-model-deploy",
    app_tool_deploy: "path-app-tool-deploy",
    user_admin: "path-user-admin",
  };

  const state = {
    activePage: "run-tests",
    activeRunMode: "quick",
    activeRunId: null,
    customScenarioCatalog: [],
    restoredCustomSelections: [],
    selectedCustomScenarios: new Set(),
    runs: [],
    lastRunsFingerprint: "",
    shots: new Map(),
    events: [],
    refreshTimer: null,
    ws: null,
    wsManualClose: false,
    wsReconnectTimer: null,
    wsReconnectAttempt: 0,
    wsTargetRunId: null,
    galleryItems: [],
    galleryIndex: 0,
    settings: {
      defaultUrl: "",
      defaultUser: "admin",
      defaultPassword: "",
      rememberSecrets: false,
      autoOpenMonitor: true,
      runsRefreshInterval: 5,
    },
  };

  const el = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function listToCsv(arr) {
    return (arr || []).join(",");
  }

  function csvToList(value) {
    return String(value || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
  }

  function uniqList(items) {
    const out = [];
    const seen = new Set();
    (items || []).forEach((item) => {
      if (!item || seen.has(item)) {
        return;
      }
      seen.add(item);
      out.push(item);
    });
    return out;
  }

  function toInt(id) {
    return parseInt(el(id).value || "0", 10);
  }

  function trimOrNull(id) {
    const value = String(el(id).value || "").trim();
    return value || null;
  }

  function setInlineMessage(id, text, cls = "") {
    const node = el(id);
    if (!node) {
      return;
    }
    node.textContent = text;
    node.className = `inline-message ${cls}`.trim();
  }

  function toast(text, cls = "info", ttlMs = 3600) {
    const stack = el("toast-stack");
    if (!stack) {
      return;
    }
    const node = document.createElement("div");
    node.className = `toast ${cls}`;
    node.textContent = text;
    stack.appendChild(node);
    window.setTimeout(() => {
      node.remove();
    }, ttlMs);
  }

  async function copyToClipboard(text, successLabel = "Copied to clipboard.") {
    if (!text) {
      toast("Nothing to copy.", "warn");
      return;
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      toast(successLabel, "ok");
    } catch {
      toast("Clipboard copy failed.", "err");
    }
  }

  async function apiJson(url, options = {}) {
    const res = await fetch(url, options);
    const bodyText = await res.text();
    let parsed;
    if (bodyText && bodyText.trim()) {
      try {
        parsed = JSON.parse(bodyText);
      } catch {
        parsed = { detail: bodyText };
      }
    } else {
      parsed = {};
    }
    if (!res.ok) {
      const error = new Error(parsed.detail || `Request failed (${res.status})`);
      error.status = res.status;
      error.payload = parsed;
      throw error;
    }
    return parsed;
  }

  async function withButtonLock(button, labelWhileRunning, fn) {
    if (!button || button.dataset.loading === "1") {
      return;
    }
    const original = button.textContent;
    button.dataset.loading = "1";
    button.disabled = true;
    button.textContent = labelWhileRunning;
    try {
      await fn();
    } finally {
      button.textContent = original;
      button.disabled = false;
      button.dataset.loading = "0";
    }
  }

  function applyTabKeyboard(tablistEl, selector, onActivate) {
    if (!tablistEl) {
      return;
    }
    tablistEl.addEventListener("keydown", (evt) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(evt.key)) {
        return;
      }
      const tabs = Array.from(tablistEl.querySelectorAll(selector));
      const current = document.activeElement;
      const idx = tabs.indexOf(current);
      if (idx < 0) {
        return;
      }
      evt.preventDefault();
      let next = idx;
      if (evt.key === "ArrowRight") {
        next = (idx + 1) % tabs.length;
      } else if (evt.key === "ArrowLeft") {
        next = (idx - 1 + tabs.length) % tabs.length;
      } else if (evt.key === "Home") {
        next = 0;
      } else if (evt.key === "End") {
        next = tabs.length - 1;
      }
      tabs[next].focus();
      onActivate(tabs[next]);
    });
  }

  function switchPage(page) {
    state.activePage = page;
    document.querySelectorAll(".top-tab").forEach((tab) => {
      const active = tab.dataset.page === page;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.setAttribute("tabindex", active ? "0" : "-1");
    });
    document.querySelectorAll(".page").forEach((panel) => {
      const active = panel.id === `page-${page}`;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
    queuePersistState();
  }

  function switchRunMode(mode) {
    state.activeRunMode = mode;
    document.querySelectorAll(".subtab").forEach((tab) => {
      const active = tab.dataset.mode === mode;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.setAttribute("tabindex", active ? "0" : "-1");
    });
    document.querySelectorAll(".subpanel").forEach((panel) => {
      const active = panel.id === `panel-${mode}`;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
    queuePersistState();
  }

  function selectedPathScenarios() {
    const combined = [];
    Object.entries(PATH_INPUTS).forEach(([pathKey, inputId]) => {
      if (el(inputId).checked) {
        combined.push(...(SCENARIO_PATHS[pathKey]?.scenarios || []));
      }
    });
    return uniqList(combined);
  }

  function selectedCustomScenarioNames() {
    return state.customScenarioCatalog
      .filter((scenario) => state.selectedCustomScenarios.has(scenario.name))
      .map((scenario) => scenario.name);
  }

  function updatePathPreview() {
    const pathScenarios = selectedPathScenarios();
    if (pathScenarios.length === 0) {
      el("path-scenarios-preview").textContent =
        "No path selected. Pick saved custom scenarios or add names manually.";
      return;
    }
    el("path-scenarios-preview").textContent = `Selected path scenarios: ${pathScenarios.join(", ")}`;
  }

  function updateCustomScenarioPreview() {
    const selected = selectedCustomScenarioNames();
    el("custom-scenarios-count").textContent = `${state.customScenarioCatalog.length} loaded · ${selected.length} selected`;
    el("custom-scenarios-preview").textContent =
      selected.length > 0 ? `Selected custom scenarios: ${selected.join(", ")}` : "No custom scenarios selected.";
  }

  function setSelectedCustomScenarios(names) {
    const wanted = new Set(names || []);
    state.selectedCustomScenarios.clear();
    state.customScenarioCatalog.forEach((scenario) => {
      if (wanted.has(scenario.name)) {
        state.selectedCustomScenarios.add(scenario.name);
      }
    });
    renderCustomScenarioPicker();
    updateCustomScenarioPreview();
  }

  function renderCustomScenarioPicker() {
    const container = el("custom-scenarios-picker");
    if (state.customScenarioCatalog.length === 0) {
      container.innerHTML = '<div class="scenario-empty">No custom scenarios yet. Build one in Build Scenarios.</div>';
      updateCustomScenarioPreview();
      return;
    }

    container.innerHTML = "";
    state.customScenarioCatalog.forEach((scenario) => {
      const selected = state.selectedCustomScenarios.has(scenario.name);
      const card = document.createElement("div");
      card.className = `scenario-chip${selected ? " selected" : ""}`;
      const tags = Array.isArray(scenario.tags) ? scenario.tags.filter(Boolean) : [];
      card.innerHTML = `
        <label>
          <input type="checkbox" ${selected ? "checked" : ""} />
          <span>
            <span class="scenario-chip-name">${escapeHtml(scenario.name)}</span>
            <span class="scenario-chip-meta">${escapeHtml(scenario.description || "No description")} (${scenario.step_count || 0} steps)</span>
            ${
              tags.length
                ? `<span class="scenario-chip-tags">${tags
                    .map((tag) => `<span class="scenario-chip-tag">${escapeHtml(tag)}</span>`)
                    .join("")}</span>`
                : ""
            }
          </span>
        </label>
      `;
      const checkbox = card.querySelector('input[type="checkbox"]');
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          state.selectedCustomScenarios.add(scenario.name);
        } else {
          state.selectedCustomScenarios.delete(scenario.name);
        }
        card.classList.toggle("selected", checkbox.checked);
        updateCustomScenarioPreview();
        queuePersistState();
      });
      container.appendChild(card);
    });

    updateCustomScenarioPreview();
  }

  function refreshCustomScenarioSelect() {
    const select = el("custom-run-scenario-select");
    select.innerHTML = "";
    if (state.customScenarioCatalog.length === 0) {
      select.innerHTML = '<option value="">No saved scenarios</option>';
      return;
    }
    select.appendChild(new Option("Choose a scenario", ""));
    state.customScenarioCatalog.forEach((scenario) => {
      select.appendChild(new Option(`${scenario.name} (${scenario.step_count || 0} steps)`, scenario.name));
    });
  }

  function renderBuilderScenarioList() {
    const container = el("builder-scenario-list");
    if (state.customScenarioCatalog.length === 0) {
      container.innerHTML = '<div class="sub">No custom scenarios yet.</div>';
      return;
    }
    container.innerHTML = "";
    state.customScenarioCatalog.forEach((scenario) => {
      const div = document.createElement("div");
      div.className = "path-item";
      div.innerHTML = `
        <span>
          <span class="path-title">${escapeHtml(scenario.name)}</span>
          <span class="path-desc">${escapeHtml(scenario.description || "No description")} (${scenario.step_count || 0} steps)</span>
          <span class="path-desc">${escapeHtml((scenario.tags || []).join(", "))}</span>
        </span>
      `;
      container.appendChild(div);
    });
  }

  function applyCustomScenarioCatalog(scenarios) {
    const previous = new Set(state.selectedCustomScenarios);
    state.customScenarioCatalog = (scenarios || [])
      .filter((item) => item && item.name)
      .sort((a, b) => String(a.name).localeCompare(String(b.name)));

    state.selectedCustomScenarios.clear();
    const seed = state.restoredCustomSelections.length
      ? new Set(state.restoredCustomSelections)
      : previous;
    state.customScenarioCatalog.forEach((scenario) => {
      if (seed.has(scenario.name)) {
        state.selectedCustomScenarios.add(scenario.name);
      }
    });
    state.restoredCustomSelections = [];

    renderCustomScenarioPicker();
    refreshCustomScenarioSelect();
    renderBuilderScenarioList();
  }

  async function fetchBuilderScenarios() {
    const data = await apiJson("/builder/scenarios");
    return Array.isArray(data.scenarios) ? data.scenarios : [];
  }

  async function refreshBuilderScenarios(showToast = true) {
    try {
      const scenarios = await fetchBuilderScenarios();
      applyCustomScenarioCatalog(scenarios);
      if (showToast) {
        toast("Scenario catalog refreshed.", "ok", 1800);
      }
    } catch {
      applyCustomScenarioCatalog([]);
      if (showToast) {
        toast("Could not load saved scenarios.", "err");
      }
    }
  }

  function inferSelectedPathsFromScenarios(scenarios) {
    const selected = [];
    const scenarioSet = new Set(scenarios || []);
    Object.entries(SCENARIO_PATHS).forEach(([pathKey, pathCfg]) => {
      const hasAny = (pathCfg.scenarios || []).some((name) => scenarioSet.has(name));
      if (hasAny) {
        selected.push(pathKey);
      }
    });
    return selected;
  }

  function applyScenarioSelections(scenarios, selectedPaths) {
    const scenarioList = uniqList(scenarios || []);
    const pathScenarioSet = new Set();
    (selectedPaths || []).forEach((pathKey) => {
      (SCENARIO_PATHS[pathKey]?.scenarios || []).forEach((name) => pathScenarioSet.add(name));
    });
    const customScenarioSet = new Set(state.customScenarioCatalog.map((item) => item.name));
    const selectedCustom = [];
    const manualEntries = [];

    scenarioList.forEach((scenarioName) => {
      if (pathScenarioSet.has(scenarioName)) {
        return;
      }
      if (customScenarioSet.has(scenarioName)) {
        selectedCustom.push(scenarioName);
      } else {
        manualEntries.push(scenarioName);
      }
    });

    setSelectedCustomScenarios(selectedCustom);
    el("manual-scenarios").value = listToCsv(manualEntries);
  }

  function setSelectedPaths(pathKeys) {
    const selected = new Set(pathKeys || []);
    Object.entries(PATH_INPUTS).forEach(([pathKey, inputId]) => {
      el(inputId).checked = selected.has(pathKey);
    });
    updatePathPreview();
  }

  function autoDistribute(total, ids) {
    const base = Math.floor(total / ids.length);
    let remainder = total % ids.length;
    ids.forEach((id) => {
      let value = base;
      if (remainder > 0) {
        value += 1;
        remainder -= 1;
      }
      el(id).value = String(value);
    });
  }

  function updateDistributionTotals() {
    const concurrent = toInt("load-concurrent");
    const roleTotal = toInt("role-admin") + toInt("role-editor") + toInt("role-viewer");
    const browserTotal = toInt("browser-chromium") + toInt("browser-firefox") + toInt("browser-webkit");

    const roleNode = el("role-total");
    const browserNode = el("browser-total");
    roleNode.textContent = `${roleTotal} / ${concurrent}`;
    browserNode.textContent = `${browserTotal} / ${concurrent}`;
    roleNode.classList.toggle("bad", roleTotal !== concurrent);
    browserNode.classList.toggle("bad", browserTotal !== concurrent);
  }

  function getWeightRowsFromDom() {
    return Array.from(el("weight-rows").querySelectorAll(".weight-row")).map((row) => {
      const name = row.querySelector("input[data-role='scenario']").value.trim();
      const weight = parseInt(row.querySelector("input[data-role='weight']").value || "0", 10);
      return { scenario: name, weight };
    });
  }

  function renderWeightRows(rows) {
    const target = el("weight-rows");
    const normalized = rows && rows.length ? rows : [{ scenario: "", weight: 1 }];
    target.innerHTML = "";
    normalized.forEach((row) => {
      const item = document.createElement("div");
      item.className = "weight-row";
      item.innerHTML = `
        <div class="field">
          <label>Scenario</label>
          <input data-role="scenario" placeholder="login" value="${escapeHtml(row.scenario || "")}" />
        </div>
        <div class="field">
          <label>Weight</label>
          <input data-role="weight" type="number" min="0" value="${Number.isFinite(row.weight) ? row.weight : 1}" />
        </div>
        <button type="button" class="btn-danger btn-mini" data-role="remove">Remove</button>
      `;
      item.querySelector("[data-role='remove']").addEventListener("click", () => {
        item.remove();
        if (el("weight-rows").children.length === 0) {
          renderWeightRows([{ scenario: "", weight: 1 }]);
        }
        queuePersistState();
      });
      target.appendChild(item);
    });
  }

  function buildScenarioWeightsFromRows() {
    const out = {};
    getWeightRowsFromDom().forEach((row) => {
      if (!row.scenario || row.weight <= 0) {
        return;
      }
      out[row.scenario] = row.weight;
    });
    return out;
  }

  function applyProfile(name) {
    const p = profiles[name];
    if (!p) {
      return;
    }

    el("load-concurrent").value = p.concurrent_users;
    el("load-duration").value = p.duration_seconds;
    el("load-ramp").value = p.ramp_up_seconds;
    el("load-exploratory").value = p.exploratory_pct;
    el("role-admin").value = p.role_distribution.admin || 0;
    el("role-editor").value = p.role_distribution.editor || 0;
    el("role-viewer").value = p.role_distribution.viewer || 0;
    el("browser-chromium").value = p.browser_distribution.chromium || 0;
    el("browser-firefox").value = p.browser_distribution.firefox || 0;
    el("browser-webkit").value = p.browser_distribution.webkit || 0;
    el("load-os").value = listToCsv(p.os_emulation);

    const selectedPaths = p.path_selections || inferSelectedPathsFromScenarios(p.scenarios || []);
    setSelectedPaths(selectedPaths);
    applyScenarioSelections(p.scenarios || [], selectedPaths);

    el("load-vision").checked = Boolean(p.vision_enabled);

    const weightRows = Object.entries(p.scenario_weights || {}).map(([scenario, weight]) => ({ scenario, weight }));
    renderWeightRows(weightRows);
    updateDistributionTotals();
  }

  function initProfiles() {
    const select = el("load-profile");
    Object.keys(profiles).forEach((name) => {
      select.appendChild(new Option(name, name));
    });
    select.value = "smoke";
    applyProfile("smoke");
    select.addEventListener("change", () => {
      applyProfile(select.value);
      queuePersistState();
    });
  }

  function statusBadge(status) {
    return `<span class="status ${status}">${status}</span>`;
  }

  function renderRuns() {
    const tbody = el("runs-table-body");
    const empty = el("runs-empty");
    const statusFilter = el("monitor-status-filter").value;
    const query = String(el("monitor-search").value || "").trim().toLowerCase();
    const sortMode = el("monitor-sort").value;

    let rows = [...state.runs];

    if (statusFilter) {
      rows = rows.filter((run) => run.status === statusFilter);
    }
    if (query) {
      rows = rows.filter((run) => String(run.run_id || "").toLowerCase().includes(query));
    }

    rows.sort((a, b) => {
      if (sortMode === "created_asc") {
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      }
      if (sortMode === "status") {
        return String(a.status).localeCompare(String(b.status));
      }
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });

    tbody.innerHTML = "";
    if (rows.length === 0) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    rows.forEach((run) => {
      const tr = document.createElement("tr");
      tr.className = "run-row";
      tr.dataset.runId = run.run_id;
      tr.classList.toggle("selected", run.run_id === state.activeRunId);
      const testType = run.test_type || "kamiwaza";
      tr.innerHTML = `
        <td><a class="run-link" href="/runs/${run.run_id}/report" target="_blank" rel="noopener">${escapeHtml(run.run_id.slice(0, 12))}</a></td>
        <td>${escapeHtml(testType)}</td>
        <td>${statusBadge(run.status)}</td>
        <td>${run.concurrent_users}</td>
        <td>${run.completed_workers}/${run.concurrent_users}</td>
        <td>${escapeHtml(new Date(run.created_at).toLocaleString())}</td>
        <td>
          <div class="actions compact">
            <button type="button" class="btn-secondary btn-mini" data-action="inspect">Inspect</button>
            <button type="button" class="btn-danger btn-mini" data-action="delete">Delete</button>
          </div>
        </td>
      `;

      tr.addEventListener("click", (evt) => {
        if (evt.target.closest("a,button")) {
          return;
        }
        selectRun(run.run_id);
      });

      tr.querySelector("button[data-action='inspect']").addEventListener("click", () => {
        selectRun(run.run_id);
      });
      tr.querySelector("button[data-action='delete']").addEventListener("click", async () => {
        await purgeRun(run.run_id);
      });
      tbody.appendChild(tr);
    });
  }

  async function refreshRuns() {
    try {
      const runs = await apiJson("/runs");
      if (!Array.isArray(runs)) {
        return;
      }
      const fingerprint = JSON.stringify(
        runs.map((run) => [run.run_id, run.status, run.completed_workers, run.failed_workers])
      );
      state.runs = runs;
      if (fingerprint !== state.lastRunsFingerprint) {
        state.lastRunsFingerprint = fingerprint;
        renderRuns();
      }
      if (state.activeRunId && !runs.some((run) => run.run_id === state.activeRunId)) {
        state.activeRunId = null;
        closeLive(true);
        clearMonitorPanels();
        renderRuns();
      }
    } catch (err) {
      toast(err.message || "Failed to refresh runs.", "err");
    }
  }

  function clearMonitorPanels() {
    state.events = [];
    state.shots.clear();
    renderEvents();
    renderShots();
    el("run-detail-pre").textContent = "Select a run to view details.";
    el("ws-state").textContent = "WS: idle";
  }

  async function loadRunDetail() {
    if (!state.activeRunId) {
      el("run-detail-pre").textContent = "Select a run to view details.";
      return;
    }
    try {
      const data = await apiJson(`/runs/${state.activeRunId}`);
      el("run-detail-pre").textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      el("run-detail-pre").textContent = JSON.stringify(err.payload || { detail: err.message }, null, 2);
    }
  }

  function addEvent(evt) {
    if (!evt || evt.type === "heartbeat") {
      return;
    }
    state.events.unshift(evt);
    while (state.events.length > 300) {
      state.events.pop();
    }
    renderEvents();
  }

  function renderEvents() {
    const box = el("events-list");
    if (state.events.length === 0) {
      box.innerHTML = '<p class="sub">Live events appear here after selecting a run.</p>';
      return;
    }
    box.innerHTML = state.events
      .map((evt, idx) => {
        const ts = evt.ts ? new Date(evt.ts).toLocaleTimeString() : new Date().toLocaleTimeString();
        const payload = evt.payload ? JSON.stringify(evt.payload) : "{}";
        return `
          <div class="event-row">
            <div class="event-content">
              <span class="event-ts">${escapeHtml(ts)}</span>
              <span class="event-type">${escapeHtml(evt.type || "event")}</span>
              <span>${escapeHtml(payload)}</span>
            </div>
            <button type="button" class="btn-secondary btn-mini" data-event-idx="${idx}">Copy</button>
          </div>
        `;
      })
      .join("");

    box.querySelectorAll("button[data-event-idx]").forEach((button) => {
      button.addEventListener("click", () => {
        const idx = parseInt(button.dataset.eventIdx || "-1", 10);
        const item = state.events[idx];
        if (item) {
          copyToClipboard(JSON.stringify(item, null, 2), "Event copied.");
        }
      });
    });
  }

  function saveShot(path) {
    if (!state.activeRunId || !path) {
      return;
    }
    const url = `/runs/${state.activeRunId}/artifacts/${path}`;
    state.shots.set(path, { path, url, ts: Date.now() });
    renderShots();
    if (!el("lightbox").hidden) {
      updateGallery();
    }
  }

  function renderShots() {
    const container = el("shots-grid");
    state.galleryItems = Array.from(state.shots.values()).sort((a, b) => b.ts - a.ts);
    if (state.galleryItems.length === 0) {
      container.innerHTML = '<p class="sub">Screenshots will appear here during a run.</p>';
      return;
    }
    container.innerHTML = "";
    state.galleryItems.forEach((item, idx) => {
      const card = document.createElement("div");
      card.className = "shot";
      card.innerHTML = `<img src="${item.url}" alt="${escapeHtml(item.path)}" loading="lazy" /><p>${escapeHtml(item.path)}</p>`;
      card.addEventListener("click", () => openGallery(idx));
      container.appendChild(card);
    });
  }

  function openGallery(idx) {
    if (!state.galleryItems.length) {
      return;
    }
    state.galleryIndex = idx;
    updateGallery();
    const lb = el("lightbox");
    lb.hidden = false;
    lb.classList.add("open");
  }

  function closeGallery() {
    const lb = el("lightbox");
    lb.classList.remove("open");
    lb.hidden = true;
  }

  function updateGallery() {
    const item = state.galleryItems[state.galleryIndex];
    if (!item) {
      return;
    }
    el("lb-img").src = item.url;
    el("lb-caption").textContent = item.path;
    el("lb-counter").textContent = `${state.galleryIndex + 1} / ${state.galleryItems.length}`;
    el("lb-prev").disabled = state.galleryIndex <= 0;
    el("lb-next").disabled = state.galleryIndex >= state.galleryItems.length - 1;
  }

  function closeLive(manual = true) {
    state.wsManualClose = manual;
    if (state.wsReconnectTimer) {
      window.clearTimeout(state.wsReconnectTimer);
      state.wsReconnectTimer = null;
    }
    if (state.ws) {
      try {
        state.ws.close();
      } catch {
        // ignore close failures
      }
      state.ws = null;
    }
    if (manual) {
      el("ws-state").textContent = "WS: idle";
    }
  }

  function scheduleWsReconnect() {
    if (state.wsManualClose || !state.wsTargetRunId || state.wsReconnectTimer) {
      return;
    }
    state.wsReconnectAttempt += 1;
    const delay = Math.min(30000, 1000 * 2 ** (state.wsReconnectAttempt - 1));
    el("ws-state").textContent = `WS: reconnecting in ${Math.ceil(delay / 1000)}s`;
    state.wsReconnectTimer = window.setTimeout(() => {
      state.wsReconnectTimer = null;
      connectLive(state.wsTargetRunId);
    }, delay);
  }

  function connectLive(runId) {
    if (!runId) {
      closeLive(true);
      return;
    }
    closeLive(false);
    state.wsManualClose = false;
    state.wsTargetRunId = runId;
    el("ws-state").textContent = "WS: connecting";
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${location.host}/live/${runId}`);
    state.ws = ws;

    ws.onopen = () => {
      state.wsReconnectAttempt = 0;
      el("ws-state").textContent = "WS: connected";
    };

    ws.onerror = () => {
      el("ws-state").textContent = "WS: error";
    };

    ws.onclose = () => {
      if (state.wsManualClose) {
        el("ws-state").textContent = "WS: idle";
        return;
      }
      el("ws-state").textContent = "WS: disconnected";
      scheduleWsReconnect();
    };

    ws.onmessage = (msg) => {
      try {
        const evt = JSON.parse(msg.data);
        addEvent(evt);
        if (evt.type === "worker.screenshot" && evt.payload && evt.payload.screenshot) {
          saveShot(evt.payload.screenshot);
        }
        if (evt.type === "stream.complete") {
          loadRunDetail();
          refreshRuns();
        }
      } catch {
        // ignore malformed websocket payloads
      }
    };
  }

  async function selectRun(runId) {
    if (!runId) {
      return;
    }
    if (state.activeRunId !== runId) {
      state.events = [];
      state.shots.clear();
      renderEvents();
      renderShots();
    }
    state.activeRunId = runId;
    renderRuns();
    await loadRunDetail();
    connectLive(runId);
    queuePersistState();
  }

  async function stopRun() {
    if (!state.activeRunId) {
      toast("Select a run first.", "warn");
      return;
    }
    try {
      await apiJson(`/runs/${state.activeRunId}`, { method: "DELETE" });
      toast(`Run ${state.activeRunId.slice(0, 12)} stop requested.`, "warn");
      await Promise.all([refreshRuns(), loadRunDetail()]);
    } catch (err) {
      toast(err.message || "Failed to stop run.", "err");
    }
  }

  async function purgeRun(runId) {
    if (!runId) {
      return;
    }
    if (!window.confirm(`Delete run ${runId.slice(0, 12)} and all artifacts?`)) {
      return;
    }
    try {
      await apiJson(`/runs/${runId}/purge`, { method: "DELETE" });
      if (state.activeRunId === runId) {
        state.activeRunId = null;
        closeLive(true);
        clearMonitorPanels();
      }
      toast(`Run ${runId.slice(0, 12)} deleted.`, "ok");
      await refreshRuns();
      await loadRunDetail();
      queuePersistState();
    } catch (err) {
      toast(err.message || "Failed to delete run.", "err");
    }
  }

  function openReport() {
    if (!state.activeRunId) {
      toast("Select a run first.", "warn");
      return;
    }
    window.open(`/runs/${state.activeRunId}/report`, "_blank", "noopener");
  }

  function buildQuickPayload() {
    const extensionUrl = String(el("quick-url").value || "").trim();
    if (!extensionUrl) {
      throw new Error("Extension URL is required.");
    }
    const username = String(el("quick-username").value || "").trim() || "admin";
    const password = String(el("quick-password").value || "").trim() || "kamiwaza";
    const message = String(el("quick-message").value || "").trim();

    return {
      concurrent_users: 1,
      role_distribution: { admin: 1 },
      browser_distribution: { chromium: 1 },
      os_emulation: ["win-chrome"],
      scenarios: ["kaizen_chat"],
      scenario_weights: { kaizen_chat: 1 },
      duration_seconds: toInt("quick-duration"),
      ramp_up_seconds: 0,
      vision_enabled: el("quick-vision").checked,
      exploratory_pct: 0,
      extension_url: extensionUrl,
      skip_user_provisioning: true,
      single_iteration: true,
      kamiwaza_url: extensionUrl,
      kamiwaza_admin_user: username,
      kamiwaza_admin_password: password,
      test_message: message || null,
    };
  }

  function buildLoadPayload() {
    const selectedPathScenarioNames = selectedPathScenarios();
    const selectedCustomNames = selectedCustomScenarioNames();
    const manualScenarioNames = csvToList(el("manual-scenarios").value);
    const scenarios = uniqList([...selectedPathScenarioNames, ...selectedCustomNames, ...manualScenarioNames]);

    const payload = {
      concurrent_users: toInt("load-concurrent"),
      role_distribution: {
        admin: toInt("role-admin"),
        editor: toInt("role-editor"),
        viewer: toInt("role-viewer"),
      },
      browser_distribution: {
        chromium: toInt("browser-chromium"),
        firefox: toInt("browser-firefox"),
        webkit: toInt("browser-webkit"),
      },
      os_emulation: csvToList(el("load-os").value),
      scenarios,
      scenario_weights: buildScenarioWeightsFromRows(),
      component: trimOrNull("load-component"),
      kamiwaza_url: trimOrNull("load-url"),
      kamiwaza_admin_user: trimOrNull("load-admin-user"),
      kamiwaza_admin_password: trimOrNull("load-admin-password"),
      kamiwaza_admin_token: trimOrNull("load-admin-token"),
      duration_seconds: toInt("load-duration"),
      ramp_up_seconds: toInt("load-ramp"),
      vision_enabled: el("load-vision").checked,
      exploratory_pct: parseFloat(el("load-exploratory").value || "0"),
    };

    const roleSum = Object.values(payload.role_distribution).reduce((a, b) => a + b, 0);
    const browserSum = Object.values(payload.browser_distribution).reduce((a, b) => a + b, 0);

    if (payload.concurrent_users < 1) {
      throw new Error("Concurrent users must be at least 1.");
    }
    if (!payload.kamiwaza_url) {
      throw new Error("Kamiwaza URL is required.");
    }
    if (payload.scenarios.length < 1) {
      throw new Error("Pick at least one scenario path, saved custom scenario, or additional scenario.");
    }
    if (roleSum !== payload.concurrent_users) {
      throw new Error(`Role distribution total (${roleSum}) must equal concurrent users (${payload.concurrent_users}).`);
    }
    if (browserSum !== payload.concurrent_users) {
      throw new Error(
        `Browser distribution total (${browserSum}) must equal concurrent users (${payload.concurrent_users}).`
      );
    }
    return payload;
  }

  function buildCustomRunPayload() {
    const scenario = String(el("custom-run-scenario-select").value || "").trim();
    if (!scenario) {
      throw new Error("Select a saved scenario.");
    }
    const targetUrl = String(el("custom-run-url").value || "").trim();
    if (!targetUrl) {
      throw new Error("Target App URL is required.");
    }
    const username = String(el("custom-run-username").value || "").trim() || "admin";
    const password = String(el("custom-run-password").value || "").trim() || "kamiwaza";

    return {
      concurrent_users: 1,
      role_distribution: { admin: 1 },
      browser_distribution: { chromium: 1 },
      os_emulation: ["win-chrome"],
      scenarios: [scenario],
      scenario_weights: {},
      duration_seconds: toInt("custom-run-duration"),
      ramp_up_seconds: 0,
      vision_enabled: false,
      exploratory_pct: 0,
      single_iteration: true,
      skip_user_provisioning: true,
      kamiwaza_url: targetUrl,
      kamiwaza_admin_user: username,
      kamiwaza_admin_password: password,
    };
  }

  async function afterRunStarted(runId, messageTargetId) {
    state.activeRunId = runId;
    setInlineMessage(messageTargetId, `Run ${runId} started.`, "ok");
    toast(`Run ${runId.slice(0, 12)} started.`, "ok");
    await refreshRuns();
    if (state.settings.autoOpenMonitor) {
      switchPage("monitor");
    }
    await selectRun(runId);
    queuePersistState();
  }

  async function startQuickRun() {
    const button = el("quick-run-btn");
    await withButtonLock(button, "Starting...", async () => {
      try {
        const payload = buildQuickPayload();
        setInlineMessage("quick-msg", "Starting quick chat test...", "warn");
        const data = await apiJson("/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        await afterRunStarted(data.run_id, "quick-msg");
      } catch (err) {
        setInlineMessage("quick-msg", err.message || String(err), "err");
        toast(err.message || "Failed to start quick run.", "err");
      }
    });
  }

  async function startLoadRun() {
    const button = el("load-run-btn");
    await withButtonLock(button, "Starting...", async () => {
      try {
        const payload = buildLoadPayload();
        setInlineMessage("load-msg", "Starting load test...", "warn");
        const data = await apiJson("/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        await afterRunStarted(data.run_id, "load-msg");
      } catch (err) {
        setInlineMessage("load-msg", err.message || String(err), "err");
        toast(err.message || "Failed to start load run.", "err");
      }
    });
  }

  async function startCustomRun() {
    const button = el("custom-run-btn");
    await withButtonLock(button, "Starting...", async () => {
      try {
        const payload = buildCustomRunPayload();
        setInlineMessage("custom-run-msg", "Starting custom scenario run...", "warn");
        const data = await apiJson("/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        await afterRunStarted(data.run_id, "custom-run-msg");
      } catch (err) {
        setInlineMessage("custom-run-msg", err.message || String(err), "err");
        toast(err.message || "Failed to start custom run.", "err");
      }
    });
  }

  async function detectBuilderBackend() {
    const select = el("builder-backend-select");
    const badge = el("builder-backend-badge");
    try {
      const data = await apiJson("/builder/backends");
      select.innerHTML = "";
      if (Array.isArray(data.backends) && data.backends.length > 0) {
        data.backends.forEach((backend) => {
          const opt = new Option(backend, backend, false, backend === data.active);
          select.appendChild(opt);
        });
        badge.textContent = `${data.backends.length} backend${data.backends.length > 1 ? "s" : ""} available`;
      } else {
        select.innerHTML = '<option value="">none available</option>';
        badge.textContent = "No LLM backend available";
      }
    } catch {
      select.innerHTML = '<option value="">error</option>';
      badge.textContent = "Error detecting backend";
    }
  }

  function truncateLogValue(value, maxLen = 8000) {
    const text = String(value || "");
    if (text.length <= maxLen) {
      return text;
    }
    return `${text.slice(0, maxLen)}\n...[truncated ${text.length - maxLen} chars]`;
  }

  function normalizeLogPayload(payload) {
    if (!payload || typeof payload !== "object") {
      return payload;
    }
    const out = { ...payload };
    if (typeof out.raw_response === "string") {
      out.raw_response = truncateLogValue(out.raw_response, 12000);
    }
    if (typeof out.yaml_preview === "string") {
      out.yaml_preview = truncateLogValue(out.yaml_preview, 5000);
    }
    return out;
  }

  function clearBuilderTranscript() {
    const box = el("builder-transcript");
    if (!box) {
      return;
    }
    box.innerHTML = "";
  }

  function appendBuilderTranscript(entry) {
    const box = el("builder-transcript");
    if (!box) {
      return;
    }

    const ts = entry.ts ? new Date(entry.ts).toLocaleTimeString() : new Date().toLocaleTimeString();
    const eventName = entry.event || entry.type || "log";
    const message = String(entry.message || "");
    const row = document.createElement("div");
    row.className = "builder-log-row";
    row.innerHTML = `<span class="builder-log-ts">${escapeHtml(ts)}</span><span class="builder-log-event">${escapeHtml(
      eventName
    )}</span>${escapeHtml(message)}`;

    const payload = normalizeLogPayload(entry.payload);
    if (payload && Object.keys(payload).length > 0) {
      const pre = document.createElement("pre");
      pre.className = "builder-log-pre";
      pre.textContent = JSON.stringify(payload, null, 2);
      row.appendChild(pre);
    }

    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
  }

  async function generateScenarioExplore() {
    const targetUrl = String(el("builder-target-url").value || "").trim();
    const prompt = String(el("builder-prompt").value || "").trim();
    if (!targetUrl) {
      setInlineMessage("builder-message", "Target App URL is required for exploration.", "err");
      return;
    }
    if (!prompt) {
      setInlineMessage("builder-message", "Describe what you want to test.", "warn");
      return;
    }

    const button = el("builder-generate-btn");
    await withButtonLock(button, "Exploring...", async () => {
      setInlineMessage("builder-message", "Exploring app with LLM... this can take 2-5 minutes.", "warn");
      el("builder-progress").hidden = false;
      el("builder-progress-text").textContent = "Starting exploration...";
      clearBuilderTranscript();
      appendBuilderTranscript({ event: "session", message: "Started browser exploration stream." });

      try {
        const res = await fetch("/builder/explore", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_url: targetUrl,
            task: prompt,
            username: String(el("builder-username").value || "admin").trim(),
            password: String(el("builder-password").value || "").trim(),
            backend: el("builder-backend-select").value || null,
          }),
        });

        if (!res.ok) {
          const body = await res.text();
          let detail = `Explorer request failed (${res.status}).`;
          if (body) {
            try {
              detail = JSON.parse(body).detail || detail;
            } catch {
              detail = body;
            }
          }
          throw new Error(detail);
        }

        if (!res.body) {
          throw new Error("Explorer response stream unavailable.");
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let finalData = null;

        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) {
              continue;
            }
            try {
              const evt = JSON.parse(line.slice(6));
              if (evt.type === "step") {
                el("builder-progress-text").textContent = `Step ${evt.step}: ${evt.message}`;
                appendBuilderTranscript({
                  type: "step",
                  event: `step.${evt.step}`,
                  message: evt.message || "",
                  ts: evt.ts,
                });
              } else if (evt.type === "log") {
                el("builder-progress-text").textContent = evt.message || "Streaming exploration log...";
                appendBuilderTranscript(evt);
              } else if (evt.type === "complete") {
                finalData = evt;
                appendBuilderTranscript({
                  type: "complete",
                  event: "complete",
                  message: `Exploration completed (${evt.steps_taken || 0} steps).`,
                });
              } else if (evt.type === "error") {
                setInlineMessage("builder-message", `Explorer error: ${evt.message}`, "err");
                appendBuilderTranscript({
                  type: "error",
                  event: "error",
                  message: evt.message || "Explorer error",
                });
              }
            } catch {
              // ignore malformed stream payload
            }
          }
        }

        if (!finalData) {
          throw new Error("Explorer finished without a result payload.");
        }

        if (finalData.errors && finalData.errors.length) {
          setInlineMessage(
            "builder-message",
            `Explored ${finalData.steps_taken} steps. Warnings: ${finalData.errors.join("; ")}`,
            finalData.yaml_content ? "warn" : "err"
          );
        } else {
          setInlineMessage(
            "builder-message",
            `Explored ${finalData.steps_taken} steps. Scenario generated${finalData.success ? " (task completed)" : ""}.`,
            "ok"
          );
        }

        if (finalData.yaml_content) {
          el("builder-yaml").value = finalData.yaml_content;
          el("builder-save-name").value = finalData.name || String(el("builder-name").value || "").trim();
          el("builder-editor-section").hidden = false;
        }
      } catch (err) {
        setInlineMessage("builder-message", err.message || String(err), "err");
        toast(err.message || "Explorer failed.", "err");
        appendBuilderTranscript({
          type: "error",
          event: "error",
          message: err.message || String(err),
        });
      } finally {
        el("builder-progress-text").textContent = "Exploration stream finished.";
      }
    });
  }

  async function generateScenarioBlind() {
    const prompt = String(el("builder-prompt").value || "").trim();
    if (!prompt) {
      setInlineMessage("builder-message", "Describe what you want to test.", "warn");
      return;
    }

    const button = el("builder-generate-blind-btn");
    await withButtonLock(button, "Generating...", async () => {
      try {
        const data = await apiJson("/builder/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            prompt,
            name: String(el("builder-name").value || "").trim() || null,
            tags: csvToList(el("builder-tags").value),
            backend: el("builder-backend-select").value || null,
          }),
        });

        if (data.errors && data.errors.length > 0) {
          setInlineMessage("builder-message", `Warnings: ${data.errors.join("; ")}`, data.yaml_content ? "warn" : "err");
        } else {
          setInlineMessage("builder-message", `Scenario generated via ${data.backend_used}.`, "ok");
        }

        if (data.yaml_content) {
          el("builder-yaml").value = data.yaml_content;
          el("builder-save-name").value = data.name || String(el("builder-name").value || "").trim();
          el("builder-editor-section").hidden = false;
        }
      } catch (err) {
        setInlineMessage("builder-message", err.message || String(err), "err");
        toast(err.message || "Scenario generation failed.", "err");
      }
    });
  }

  async function saveScenario() {
    const name = String(el("builder-save-name").value || "").trim();
    const yamlContent = String(el("builder-yaml").value || "").trim();
    if (!name) {
      setInlineMessage("builder-save-message", "Name is required.", "warn");
      return false;
    }
    if (!yamlContent) {
      setInlineMessage("builder-save-message", "YAML content is empty.", "warn");
      return false;
    }

    try {
      const data = await apiJson("/builder/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, yaml_content: yamlContent }),
      });
      if (data.saved) {
        setInlineMessage("builder-save-message", `Saved to ${data.path}.`, "ok");
        await refreshBuilderScenarios();
        return true;
      }
      setInlineMessage("builder-save-message", `Save failed: ${(data.errors || []).join("; ")}`, "err");
      return false;
    } catch (err) {
      setInlineMessage("builder-save-message", err.message || String(err), "err");
      return false;
    }
  }

  async function saveAndRunScenario() {
    const button = el("builder-save-run-btn");
    await withButtonLock(button, "Saving & starting...", async () => {
      const saved = await saveScenario();
      if (!saved) {
        return;
      }
      const name = String(el("builder-save-name").value || "").trim();
      const targetUrl =
        String(el("builder-target-url").value || "").trim() ||
        String(el("load-url").value || "").trim() ||
        String(el("quick-url").value || "").trim();

      if (!targetUrl) {
        setInlineMessage("builder-save-message", "Set Target App URL before Save & Run.", "err");
        return;
      }

      const payload = {
        concurrent_users: 1,
        role_distribution: { admin: 1 },
        browser_distribution: { chromium: 1 },
        os_emulation: ["win-chrome"],
        scenarios: [name],
        scenario_weights: {},
        duration_seconds: 300,
        ramp_up_seconds: 0,
        vision_enabled: false,
        exploratory_pct: 0,
        single_iteration: true,
        skip_user_provisioning: true,
        kamiwaza_url: targetUrl,
        kamiwaza_admin_user:
          String(el("builder-username").value || "").trim() ||
          String(el("load-admin-user").value || "").trim() ||
          String(el("quick-username").value || "").trim() ||
          "admin",
        kamiwaza_admin_password:
          String(el("builder-password").value || "").trim() ||
          String(el("load-admin-password").value || "").trim() ||
          String(el("quick-password").value || "").trim() ||
          "",
      };

      try {
        const data = await apiJson("/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setInlineMessage("builder-save-message", `Run ${data.run_id} started.`, "ok");
        await afterRunStarted(data.run_id, "builder-save-message");
      } catch (err) {
        setInlineMessage("builder-save-message", err.message || String(err), "err");
      }
    });
  }

  function gatherEventLogText() {
    return state.events.map((evt) => JSON.stringify(evt, null, 2)).join("\n\n");
  }

  function captureSettings() {
    state.settings = {
      defaultUrl: String(el("setting-default-url").value || "").trim(),
      defaultUser: String(el("setting-default-user").value || "").trim() || "admin",
      defaultPassword: String(el("setting-default-password").value || "").trim(),
      rememberSecrets: Boolean(el("setting-remember-secrets").checked),
      autoOpenMonitor: Boolean(el("setting-auto-open-monitor").checked),
      runsRefreshInterval: Math.max(2, Math.min(60, toInt("setting-runs-refresh-interval") || 5)),
    };
  }

  function applySettingsToInputs() {
    el("setting-default-url").value = state.settings.defaultUrl || "";
    el("setting-default-user").value = state.settings.defaultUser || "admin";
    el("setting-default-password").value = state.settings.defaultPassword || "";
    el("setting-remember-secrets").checked = Boolean(state.settings.rememberSecrets);
    el("setting-auto-open-monitor").checked = Boolean(state.settings.autoOpenMonitor);
    el("setting-runs-refresh-interval").value = String(state.settings.runsRefreshInterval || 5);
  }

  function applyDefaultsToBlankFields() {
    const applyIfBlank = (id, value) => {
      if (!value) {
        return;
      }
      if (!String(el(id).value || "").trim()) {
        el(id).value = value;
      }
    };

    applyIfBlank("quick-url", state.settings.defaultUrl);
    applyIfBlank("load-url", state.settings.defaultUrl);
    applyIfBlank("custom-run-url", state.settings.defaultUrl);
    applyIfBlank("builder-target-url", state.settings.defaultUrl);

    applyIfBlank("quick-username", state.settings.defaultUser);
    applyIfBlank("custom-run-username", state.settings.defaultUser);
    applyIfBlank("builder-username", state.settings.defaultUser);

    applyIfBlank("quick-password", state.settings.defaultPassword);
    applyIfBlank("custom-run-password", state.settings.defaultPassword);
    applyIfBlank("builder-password", state.settings.defaultPassword);
  }

  function configureRefreshTimer() {
    if (state.refreshTimer) {
      window.clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }
    const intervalMs = Math.max(2, Number(state.settings.runsRefreshInterval || 5)) * 1000;
    state.refreshTimer = window.setInterval(() => {
      refreshRuns();
      if (state.activeRunId) {
        loadRunDetail();
      }
    }, intervalMs);
  }

  function persistedData() {
    const secretAllowed = Boolean(state.settings.rememberSecrets);
    const persistField = (id, isSecret = false) => {
      if (isSecret && !secretAllowed) {
        return "";
      }
      const node = el(id);
      if (!node) {
        return "";
      }
      if (node.type === "checkbox") {
        return Boolean(node.checked);
      }
      return node.value;
    };

    return {
      activePage: state.activePage,
      activeRunMode: state.activeRunMode,
      activeRunId: state.activeRunId,
      restoredCustomSelections: selectedCustomScenarioNames(),
      settings: { ...state.settings },
      monitor: {
        status: el("monitor-status-filter").value,
        sort: el("monitor-sort").value,
        search: el("monitor-search").value,
      },
      load: {
        profile: el("load-profile").value,
        component: persistField("load-component"),
        url: persistField("load-url"),
        concurrent: persistField("load-concurrent"),
        duration: persistField("load-duration"),
        ramp: persistField("load-ramp"),
        exploratory: persistField("load-exploratory"),
        adminUser: persistField("load-admin-user"),
        adminPassword: persistField("load-admin-password", true),
        adminToken: persistField("load-admin-token", true),
        roleAdmin: persistField("role-admin"),
        roleEditor: persistField("role-editor"),
        roleViewer: persistField("role-viewer"),
        browserChromium: persistField("browser-chromium"),
        browserFirefox: persistField("browser-firefox"),
        browserWebkit: persistField("browser-webkit"),
        os: persistField("load-os"),
        vision: persistField("load-vision"),
        manualScenarios: persistField("manual-scenarios"),
        selectedPaths: Object.entries(PATH_INPUTS)
          .filter(([, inputId]) => Boolean(el(inputId).checked))
          .map(([key]) => key),
        weights: getWeightRowsFromDom(),
        advancedOpen: el("load-advanced").open,
      },
      quick: {
        url: persistField("quick-url"),
        username: persistField("quick-username"),
        password: persistField("quick-password", true),
        message: persistField("quick-message"),
        duration: persistField("quick-duration"),
        vision: persistField("quick-vision"),
      },
      custom: {
        scenario: persistField("custom-run-scenario-select"),
        url: persistField("custom-run-url"),
        username: persistField("custom-run-username"),
        password: persistField("custom-run-password", true),
        duration: persistField("custom-run-duration"),
      },
      builder: {
        backend: persistField("builder-backend-select"),
        targetUrl: persistField("builder-target-url"),
        username: persistField("builder-username"),
        password: persistField("builder-password", true),
        prompt: persistField("builder-prompt"),
        name: persistField("builder-name"),
        tags: persistField("builder-tags"),
        yaml: persistField("builder-yaml"),
        saveName: persistField("builder-save-name"),
        editorOpen: !el("builder-editor-section").hidden,
      },
    };
  }

  let persistTimer = null;

  function queuePersistState() {
    if (persistTimer) {
      window.clearTimeout(persistTimer);
    }
    persistTimer = window.setTimeout(() => {
      try {
        captureSettings();
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persistedData()));
      } catch {
        // ignore localStorage failures
      }
    }, 200);
  }

  function restoreStateFromStorage() {
    let parsed = null;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        parsed = JSON.parse(raw);
      }
    } catch {
      parsed = null;
    }
    if (!parsed || typeof parsed !== "object") {
      return;
    }

    if (parsed.settings && typeof parsed.settings === "object") {
      state.settings = {
        ...state.settings,
        ...parsed.settings,
      };
    }
    applySettingsToInputs();

    const maybeSet = (id, value, isCheckbox = false) => {
      if (value === undefined || value === null || !el(id)) {
        return;
      }
      if (isCheckbox) {
        el(id).checked = Boolean(value);
      } else {
        el(id).value = String(value);
      }
    };

    maybeSet("quick-url", parsed.quick?.url);
    maybeSet("quick-username", parsed.quick?.username);
    maybeSet("quick-password", parsed.quick?.password);
    maybeSet("quick-message", parsed.quick?.message);
    maybeSet("quick-duration", parsed.quick?.duration);
    maybeSet("quick-vision", parsed.quick?.vision, true);

    maybeSet("load-profile", parsed.load?.profile);
    if (parsed.load?.profile && profiles[parsed.load.profile]) {
      applyProfile(parsed.load.profile);
    }
    maybeSet("load-component", parsed.load?.component);
    maybeSet("load-url", parsed.load?.url);
    maybeSet("load-concurrent", parsed.load?.concurrent);
    maybeSet("load-duration", parsed.load?.duration);
    maybeSet("load-ramp", parsed.load?.ramp);
    maybeSet("load-exploratory", parsed.load?.exploratory);
    maybeSet("load-admin-user", parsed.load?.adminUser);
    maybeSet("load-admin-password", parsed.load?.adminPassword);
    maybeSet("load-admin-token", parsed.load?.adminToken);
    maybeSet("role-admin", parsed.load?.roleAdmin);
    maybeSet("role-editor", parsed.load?.roleEditor);
    maybeSet("role-viewer", parsed.load?.roleViewer);
    maybeSet("browser-chromium", parsed.load?.browserChromium);
    maybeSet("browser-firefox", parsed.load?.browserFirefox);
    maybeSet("browser-webkit", parsed.load?.browserWebkit);
    maybeSet("load-os", parsed.load?.os);
    maybeSet("load-vision", parsed.load?.vision, true);
    maybeSet("manual-scenarios", parsed.load?.manualScenarios);
    if (parsed.load?.selectedPaths) {
      setSelectedPaths(parsed.load.selectedPaths);
    }
    if (Array.isArray(parsed.load?.weights)) {
      renderWeightRows(parsed.load.weights);
    }
    if (parsed.load?.advancedOpen) {
      el("load-advanced").open = true;
    }

    maybeSet("custom-run-scenario-select", parsed.custom?.scenario);
    maybeSet("custom-run-url", parsed.custom?.url);
    maybeSet("custom-run-username", parsed.custom?.username);
    maybeSet("custom-run-password", parsed.custom?.password);
    maybeSet("custom-run-duration", parsed.custom?.duration);

    maybeSet("builder-backend-select", parsed.builder?.backend);
    maybeSet("builder-target-url", parsed.builder?.targetUrl);
    maybeSet("builder-username", parsed.builder?.username);
    maybeSet("builder-password", parsed.builder?.password);
    maybeSet("builder-prompt", parsed.builder?.prompt);
    maybeSet("builder-name", parsed.builder?.name);
    maybeSet("builder-tags", parsed.builder?.tags);
    maybeSet("builder-yaml", parsed.builder?.yaml);
    maybeSet("builder-save-name", parsed.builder?.saveName);
    if (parsed.builder?.editorOpen && parsed.builder?.yaml) {
      el("builder-editor-section").hidden = false;
    }

    maybeSet("monitor-status-filter", parsed.monitor?.status);
    maybeSet("monitor-sort", parsed.monitor?.sort);
    maybeSet("monitor-search", parsed.monitor?.search);

    if (Array.isArray(parsed.restoredCustomSelections)) {
      state.restoredCustomSelections = parsed.restoredCustomSelections;
    }

    state.activePage = parsed.activePage || "run-tests";
    state.activeRunMode = parsed.activeRunMode || "quick";
    state.activeRunId = parsed.activeRunId || null;

    updateDistributionTotals();
    updatePathPreview();
    queuePersistState();
  }

  function resetSettings() {
    state.settings = {
      defaultUrl: "",
      defaultUser: "admin",
      defaultPassword: "",
      rememberSecrets: false,
      autoOpenMonitor: true,
      runsRefreshInterval: 5,
    };
    applySettingsToInputs();
    configureRefreshTimer();
    queuePersistState();
    setInlineMessage("settings-msg", "Settings reset to defaults.", "ok");
    toast("Settings reset.", "ok");
  }

  function initLightbox() {
    el("lb-close").addEventListener("click", closeGallery);
    el("lb-prev").addEventListener("click", () => {
      if (state.galleryIndex > 0) {
        state.galleryIndex -= 1;
        updateGallery();
      }
    });
    el("lb-next").addEventListener("click", () => {
      if (state.galleryIndex < state.galleryItems.length - 1) {
        state.galleryIndex += 1;
        updateGallery();
      }
    });
    el("lightbox").addEventListener("click", (evt) => {
      if (evt.target === el("lightbox")) {
        closeGallery();
      }
    });
    document.addEventListener("keydown", (evt) => {
      if (el("lightbox").hidden) {
        return;
      }
      if (evt.key === "Escape") {
        closeGallery();
      } else if (evt.key === "ArrowLeft" && state.galleryIndex > 0) {
        state.galleryIndex -= 1;
        updateGallery();
      } else if (evt.key === "ArrowRight" && state.galleryIndex < state.galleryItems.length - 1) {
        state.galleryIndex += 1;
        updateGallery();
      }
    });
  }

  function initEventBindings() {
    document.querySelectorAll(".top-tab").forEach((tab) => {
      tab.addEventListener("click", () => switchPage(tab.dataset.page));
    });
    document.querySelectorAll(".subtab").forEach((tab) => {
      tab.addEventListener("click", () => switchRunMode(tab.dataset.mode));
    });

    applyTabKeyboard(el("top-tabs"), ".top-tab", (tab) => switchPage(tab.dataset.page));
    applyTabKeyboard(el("run-mode-tabs"), ".subtab", (tab) => switchRunMode(tab.dataset.mode));

    el("quick-run-btn").addEventListener("click", startQuickRun);
    el("load-run-btn").addEventListener("click", startLoadRun);
    el("custom-run-btn").addEventListener("click", startCustomRun);

    el("monitor-refresh-runs").addEventListener("click", refreshRuns);
    el("monitor-status-filter").addEventListener("change", () => {
      renderRuns();
      queuePersistState();
    });
    el("monitor-sort").addEventListener("change", () => {
      renderRuns();
      queuePersistState();
    });
    el("monitor-search").addEventListener("input", () => {
      renderRuns();
      queuePersistState();
    });

    el("open-report-btn").addEventListener("click", openReport);
    el("stop-run-btn").addEventListener("click", stopRun);
    el("purge-run-btn").addEventListener("click", async () => {
      await purgeRun(state.activeRunId);
    });
    el("copy-run-detail-btn").addEventListener("click", () => {
      copyToClipboard(el("run-detail-pre").textContent || "", "Run detail copied.");
    });
    el("copy-events-btn").addEventListener("click", () => {
      copyToClipboard(gatherEventLogText(), "Events copied.");
    });

    el("builder-generate-btn").addEventListener("click", generateScenarioExplore);
    el("builder-generate-blind-btn").addEventListener("click", generateScenarioBlind);
    el("builder-save-btn").addEventListener("click", saveScenario);
    el("builder-save-run-btn").addEventListener("click", saveAndRunScenario);
    el("builder-refresh-scenarios-btn").addEventListener("click", refreshBuilderScenarios);
    el("custom-scenarios-refresh").addEventListener("click", refreshBuilderScenarios);

    el("btn-role-autofill").addEventListener("click", () => {
      autoDistribute(toInt("load-concurrent"), ["role-admin", "role-editor", "role-viewer"]);
      updateDistributionTotals();
      queuePersistState();
    });
    el("btn-browser-autofill").addEventListener("click", () => {
      autoDistribute(toInt("load-concurrent"), ["browser-chromium", "browser-firefox", "browser-webkit"]);
      updateDistributionTotals();
      queuePersistState();
    });

    [
      "load-concurrent",
      "role-admin",
      "role-editor",
      "role-viewer",
      "browser-chromium",
      "browser-firefox",
      "browser-webkit",
    ].forEach((id) => {
      el(id).addEventListener("input", () => {
        updateDistributionTotals();
        queuePersistState();
      });
    });

    Object.values(PATH_INPUTS).forEach((inputId) => {
      el(inputId).addEventListener("change", () => {
        updatePathPreview();
        queuePersistState();
      });
    });

    el("add-weight-row").addEventListener("click", () => {
      const current = getWeightRowsFromDom();
      current.push({ scenario: "", weight: 1 });
      renderWeightRows(current);
      queuePersistState();
    });

    document.body.addEventListener("input", (evt) => {
      if (evt.target.matches("input,textarea,select")) {
        queuePersistState();
      }
    });
    document.body.addEventListener("change", (evt) => {
      if (evt.target.matches("input,textarea,select,details")) {
        queuePersistState();
      }
    });

    el("settings-save-btn").addEventListener("click", () => {
      captureSettings();
      applyDefaultsToBlankFields();
      configureRefreshTimer();
      queuePersistState();
      setInlineMessage("settings-msg", "Settings saved.", "ok");
      toast("Settings saved.", "ok");
    });
    el("settings-reset-btn").addEventListener("click", resetSettings);
  }

  async function bootstrap() {
    initProfiles();
    renderWeightRows([{ scenario: "login", weight: 1 }]);
    initLightbox();
    initEventBindings();

    applySettingsToInputs();
    restoreStateFromStorage();
    applyDefaultsToBlankFields();

    switchPage(state.activePage);
    switchRunMode(state.activeRunMode);

    await detectBuilderBackend();
    await refreshBuilderScenarios(false);

    const currentProfile = el("load-profile").value;
    if (currentProfile && profiles[currentProfile]) {
      // keep persisted field overrides, but align scenario layout with selected profile first
      const selectedPaths = inferSelectedPathsFromScenarios(profiles[currentProfile].scenarios || []);
      if (!Object.values(PATH_INPUTS).some((inputId) => el(inputId).checked)) {
        setSelectedPaths(selectedPaths);
      }
      updatePathPreview();
    }

    updateDistributionTotals();

    await refreshRuns();
    if (state.activeRunId) {
      await selectRun(state.activeRunId);
    } else {
      clearMonitorPanels();
    }

    captureSettings();
    configureRefreshTimer();
    queuePersistState();
  }

  bootstrap().catch((err) => {
    const status = el("service-status");
    status.textContent = `UI error: ${err.message || String(err)}`;
    status.style.color = "var(--err)";
    toast(err.message || "UI bootstrap failed.", "err");
  });
})();
