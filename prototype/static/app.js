const state = {
  summary: null,
  chartOptions: [],
  expandedChart: "",
  jobsTimer: null,
  actions: [],
  auditEvents: [],
  chatSessions: [],
  currentChatSessionId: "",
  aiConfig: null,
  confirmResolver: null,
};

const modelOptions = [
  { value: "mimo-v2.5-pro", label: "MiMo-V2.5-Pro" },
  { value: "mimo-v2.5", label: "MiMo-V2.5" },
  { value: "mimo-v2-pro", label: "MiMo-V2-Pro" },
  { value: "mimo-v2-omni", label: "MiMo-V2-Omni" },
];

const labels = {
  delay_test_rate_okr: "延期提测率",
  delayed_test_requirements: "延期提测需求数",
  delay_online_rate: "延期上线率",
  delayed_online_requirements: "延期上线需求数",
  technical_refactor_working_hours_rate: "技术改造工时占比",
  biweekly_delivery_rate: "双周交付率",
  ai_non_deep_users: "AI 深度用户为否",
  continuous_delivery_team_space_online_requirement_rate: "持续交付占比",
};

const metricPreviewAssets = {
  delay_test_rate_okr: "/static/assets/delay_test_rate.png",
  delay_online_rate: "/static/assets/delay_online_rate.png",
  technical_refactor_working_hours_rate: "/static/assets/technical_refactor_working_hours.png",
  biweekly_delivery_rate: "/static/assets/bi_weekly_delivery_rate.png",
};

function withAssetVersion(src) {
  const version = state.summary?.asset_version || state.summary?.loaded_at || "";
  if (!src || !version) return src || "";
  const separator = src.includes("?") ? "&" : "?";
  return `${src}${separator}v=${encodeURIComponent(version)}`;
}

const actionGroupOrder = ["主流程", "单项巡检", "报告", "日期调整", "修复", "其他"];

const actionGroupLabels = {
  主流程: "主流程",
  单项巡检: "单项",
  报告: "报告",
  日期调整: "日期调整",
  修复: "修复",
  其他: "其他",
};

const actionCompactLabels = {
  daily_inspection: "日常巡检",
  daily_inspection_with_repair: "日常巡检 + 自动修复",
  friday_inspection: "周度巡检",
  okr_all: "OKR 四项",
  delay_test_rate: "延期提测率",
  delay_online_rate: "延期上线率",
  technical_refactor: "技术改造工时",
  biweekly_delivery: "双周交付率",
  ai_inspection: "AI 深度用户",
  continuous_delivery: "持续交付",
  aggregate_report: "刷新总报告",
  friday_report_text: "周报备文案",
  thursday_report: "日期调整报告",
  thursday_adjustment: "计划日期顺延",
  repair_delayed_test: "修复延期提测",
  repair_delayed_online: "修复延期上线",
};

function $(id) {
  return document.getElementById(id);
}

const defaultSettings = {
  model: "mimo-v2.5-pro",
};

function modelLabel(value) {
  return modelOptions.find((item) => item.value === value)?.label || value || "MiMo-V2.5-Pro";
}

function formAiSettings() {
  return {
    model: $("modelSelect").value || defaultSettings.model,
  };
}

function renderSettings(config = state.aiConfig) {
  const settings = config || defaultSettings;
  const currentModel = settings.model || defaultSettings.model;
  $("modelSelect").value = currentModel;
  $("chatModelBadge").textContent = modelLabel(currentModel);
}

async function loadAiConfig() {
  const res = await fetch("/api/ai-config");
  if (!res.ok) throw new Error("ai config request failed");
  state.aiConfig = await res.json();
  renderSettings(state.aiConfig);
}

async function saveSettings() {
  const res = await fetch("/api/ai-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(formAiSettings()),
  });
  if (!res.ok) return;
  state.aiConfig = await res.json();
  renderSettings(state.aiConfig);
}

function fmt(value, unit = "") {
  if (value === null || value === undefined || value === "") return "-";
  const shown = typeof value === "number" && !Number.isInteger(value)
    ? String(Number(value.toFixed(2))).replace(/\.0$/, "")
    : String(value);
  return unit === "%" ? `${shown}%` : shown;
}

function displayUnit(unit = "") {
  return ({ count: "个", hour: "人天" })[unit] || unit;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function closeConfirmModal(accepted) {
  $("confirmModal").hidden = true;
  const resolver = state.confirmResolver;
  state.confirmResolver = null;
  if (resolver) resolver(Boolean(accepted));
}

function openConfirmModal(options = {}) {
  $("confirmTitle").textContent = options.title || "确认执行";
  $("confirmDescription").textContent = options.description || "确认后将开始执行该操作。";
  $("confirmAcceptBtn").textContent = options.confirmText || "确认";
  $("confirmModal").hidden = false;
  return new Promise((resolve) => {
    state.confirmResolver = resolve;
  });
}

function openImagePreview(options = {}) {
  $("imagePreviewTitle").textContent = options.title || "截图预览";
  $("imagePreviewImage").src = options.src || "";
  $("imagePreviewImage").alt = options.title || "巡检截图";
  $("imagePreviewModal").hidden = false;
}

function closeImagePreview() {
  $("imagePreviewModal").hidden = true;
  $("imagePreviewImage").src = "";
  $("imagePreviewImage").alt = "";
}

async function loadSummary() {
  const res = await fetch("/api/summary");
  if (!res.ok) throw new Error("summary request failed");
  state.summary = await res.json();
  render();
}

async function syncPublicSite() {
  const button = $("syncStaticBtn");
  const ok = await openConfirmModal({
    title: "同步展示页",
    description: "确认后会把最新看板数据和四份报告同步生成到根目录 index.html，供静态部署使用。",
    confirmText: "确认同步",
  });
  if (!ok) return;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "同步中...";
  try {
    const res = await fetch("/api/public-site/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      throw new Error("public site sync failed");
    }
    const payload = await res.json();
    await loadSummary();
    button.textContent = "已同步";
    appendMessage("assistant", `静态展示页已同步：${payload.file || "根目录 index.html"}。`);
    window.setTimeout(() => {
      button.textContent = originalText;
      button.disabled = false;
    }, 1800);
  } catch (error) {
    button.textContent = "同步失败";
    appendMessage("assistant", "同步展示页失败，请稍后重试。");
    window.setTimeout(() => {
      button.textContent = originalText;
      button.disabled = false;
    }, 2200);
  }
}

async function loadActions() {
  const res = await fetch("/api/actions");
  if (!res.ok) throw new Error("actions request failed");
  const payload = await res.json();
  state.actions = payload.actions || [];
  renderActions();
}

function statusClass(status) {
  return ["success", "partial", "failed", "timeout", "missing"].includes(status) ? status : "";
}

function statusLabel(status) {
  return {
    success: "成功",
    partial: "部分完成",
    failed: "失败",
    timeout: "超时",
    running: "执行中",
    queued: "排队中",
    skipped: "跳过",
  }[status] || status || "-";
}

function actionLabel(action) {
  return actionCompactLabels[action] || action || "-";
}

function renderHeader(summary) {
  $("department").textContent = `${summary.display_domain || summary.department_c3 || "-"}`;
  $("range").textContent = `${summary.time_range?.start_date || "-"} ~ ${summary.time_range?.end_date || "-"}`;
  $("loadedAt").textContent = `加载 ${summary.loaded_at || "-"}`;
}

function renderOverview(summary) {
  const cards = summary.overview || [];
  $("overview").innerHTML = cards.map((card) => {
    const previewAsset = metricPreviewAssets[card.key] || "";
    const previewSrc = withAssetVersion(previewAsset);
    return `
      <article class="metric-card metric-${escapeHtml(card.indicator_type || "default")}${previewSrc ? " has-preview" : ""}">
        <div class="metric-topline">
          <span class="metric-caption">${escapeHtml(card.caption || "指标")}</span>
        </div>
        <div class="metric-label">${escapeHtml(card.label)}</div>
        <div class="metric-value">${escapeHtml(card.display_value)}${card.unit && card.unit !== "%" && card.key !== "ai_non_deep_users" ? `<span class="muted"> ${escapeHtml(displayUnit(card.unit))}</span>` : ""}</div>
        <div class="metric-foot">
          <span>${escapeHtml(card.date || "-")}</span>
          <span>${escapeHtml(card.title || "")}</span>
        </div>
        ${previewSrc ? `
          <div class="metric-preview">
            <div class="metric-preview-label">巡检截图</div>
            <img
              src="${escapeHtml(previewSrc)}"
              alt="${escapeHtml(card.label)}巡检截图"
              loading="lazy"
              data-preview-full="${escapeHtml(previewSrc)}"
              data-preview-title="${escapeHtml(card.label)}"
            />
          </div>
        ` : ""}
      </article>
    `;
  }).join("");
  $("overview").querySelectorAll(".metric-preview img[data-preview-full]").forEach((image) => {
    image.addEventListener("click", () => {
      openImagePreview({
        src: image.dataset.previewFull || "",
        title: image.dataset.previewTitle || "截图预览",
      });
    });
  });
}

function groupActions(actions) {
  return actions.reduce((groups, action) => {
    const group = action.group || "其他";
    groups[group] = groups[group] || [];
    groups[group].push(action);
    return groups;
  }, {});
}

function actionSelectLabel(action) {
  const base = actionCompactLabels[action.id] || action.title || action.id;
  const availability = action.availability || {};
  if (availability.scheduled && availability.can_run === false) {
    return `${base} · ${availability.weekday_label || "待执行日"}`;
  }
  return action.risk === "write" ? `${base} · 需确认` : base;
}

function actionCanRun(action) {
  return (action?.availability || {}).can_run !== false;
}

function actionUnavailableText(action) {
  const availability = action?.availability || {};
  return availability.reason || "当前不在该操作的执行窗口。";
}

function findAction(actionId) {
  return (state.actions || []).find((action) => action.id === actionId);
}

function applyActionAvailability() {
  document.querySelectorAll("[data-action]").forEach((button) => {
    const action = findAction(button.dataset.action || "");
    if (!action) return;
    const disabled = !actionCanRun(action);
    button.disabled = disabled;
    button.classList.toggle("is-disabled-by-schedule", disabled);
    button.title = disabled ? actionUnavailableText(action) : (action.description || "");
  });
}

function renderActions() {
  const featuredIds = [
    "daily_inspection",
    "friday_inspection",
    "thursday_adjustment",
    "repair_delayed_test",
    "repair_delayed_online",
    "aggregate_report",
  ];
  const featured = featuredIds
    .map((id) => state.actions.find((action) => action.id === id))
    .filter(Boolean);
  $("featuredActions").innerHTML = featured.length
    ? featured.map((action) => `
      <article class="action-card is-featured">
        <div class="action-title-row">
          <span class="action-title">${escapeHtml(action.title)}</span>
          <span class="risk-badge ${action.risk === "write" ? "write" : ""}">${action.risk === "write" ? "需确认" : "只读"}</span>
        </div>
        ${!actionCanRun(action) ? `<div class="action-schedule-note">${escapeHtml(actionUnavailableText(action))}</div>` : ""}
        <button type="button" data-action="${escapeHtml(action.id)}"${!actionCanRun(action) ? " disabled" : ""}>${action.risk === "write" ? "准备执行" : "执行"}</button>
      </article>
    `).join("")
    : `<div class="list-item">暂无可用功能</div>`;
  const groups = groupActions(state.actions || []);
  const orderedGroups = actionGroupOrder.filter((name) => groups[name]?.length);
  const extraGroups = Object.keys(groups).filter((name) => !orderedGroups.includes(name));
  $("moreActionSelect").innerHTML = [...orderedGroups, ...extraGroups].map((group) => `
    <optgroup label="${escapeHtml(actionGroupLabels[group] || group)}">
      ${(groups[group] || []).map((action) => `
        <option value="${escapeHtml(action.id)}">${escapeHtml(actionSelectLabel(action))}</option>
      `).join("")}
    </optgroup>
  `).join("");
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      await runAction(button.dataset.action || "", {
        forceConfirm: button.dataset.forceConfirm === "true",
        confirmTitle: button.dataset.confirmTitle || "",
        button,
      });
    });
  });
  applyActionAvailability();
}

function latestNonNull(points) {
  return [...(points || [])].reverse().find((point) => point.value !== null && point.value !== undefined) || {};
}

function findHistoryMetric(summary, key) {
  for (const indicator of summary.indicators || []) {
    const unit = indicator.unit || {};
    const points = indicator.history?.[key];
    if (points) {
      return {
        id: `${indicator.indicator_type}:${key}`,
        key,
        title: labels[key] || key,
        unit: unit[key] || points[0]?.unit || "",
        points,
      };
    }
  }
  return null;
}

function singlePoint(id, key, title, unit, date, value) {
  return {
    id,
    key,
    title,
    unit,
    points: [{ date: date || "-", value, unit }],
  };
}

function repairTrendOption(summary, repairType, indicatorType, key) {
  const repairMetric = summary.repair_metrics?.[repairType] || {};
  const focus = (summary.focus_series || []).find((item) => item.indicator_type === indicatorType);
  const focusMetric = (focus?.metrics || []).find((item) => item.key === key);
  const points = Array.isArray(focusMetric?.points) ? [...focusMetric.points] : [];
  const repairDate = repairMetric.date || summary.inspection_date;
  if (repairDate && !points.some((point) => point.date === repairDate)) {
    points.push({ date: repairDate, value: repairMetric.value ?? 0, unit: "count" });
  }
  return {
    id: `${indicatorType}:${key}`,
    key,
    title: labels[key] || repairMetric.label || key,
    unit: "count",
    points: points.length ? points : [{ date: repairDate || "-", value: repairMetric.value ?? 0, unit: "count" }],
  };
}

function buildChartOptions(summary) {
  const options = [
    repairTrendOption(summary, "delayed_test", "delay_test_rate", "delayed_test_requirements"),
    repairTrendOption(summary, "delayed_online", "delay_online_rate", "delayed_online_requirements"),
    findHistoryMetric(summary, "technical_refactor_working_hours_rate"),
    findHistoryMetric(summary, "biweekly_delivery_rate"),
  ].filter(Boolean);
  const ai = summary.ai_inspection || {};
  const delivery = summary.continuous_delivery || {};
  options.push(singlePoint(
    "ai_inspection:ai_non_deep_users",
    "ai_non_deep_users",
    labels.ai_non_deep_users,
    "count",
    ai.date || summary.inspection_date,
    ai.count ?? 0,
  ));
  options.push(singlePoint(
    "continuous_delivery:continuous_delivery_team_space_online_requirement_rate",
    "continuous_delivery_team_space_online_requirement_rate",
    labels.continuous_delivery_team_space_online_requirement_rate,
    "%",
    delivery.date || summary.inspection_date,
    delivery.metrics?.continuous_delivery_team_space_online_requirement_rate ?? 0,
  ));
  return options.slice(0, 6);
}

function renderTrendGrid(summary) {
  state.chartOptions = Array.isArray(summary.chart_options) && summary.chart_options.length
    ? summary.chart_options
    : buildChartOptions(summary);
  if (state.expandedChart && !state.chartOptions.some((item) => item.id === state.expandedChart)) {
    state.expandedChart = "";
  }
  const isExpanded = Boolean(state.expandedChart);
  $("trendGrid").className = `trend-grid${isExpanded ? " is-expanded" : ""}`;
  $("trendResetBtn").hidden = !isExpanded;
  $("chartSubtitle").textContent = "";
  $("trendGrid").innerHTML = state.chartOptions.map((option) => {
    const latest = latestNonNull(option.points || []);
    const expanded = option.id === state.expandedChart;
    const hidden = isExpanded && !expanded;
    return `
      <article class="trend-card${expanded ? " expanded" : ""}" data-chart="${escapeHtml(option.id)}"${hidden ? " hidden" : ""}>
        <div class="trend-card-head">
          <div>
            <div class="trend-title">${escapeHtml(option.title)}</div>
            <div class="trend-meta">最新值 ${escapeHtml(fmt(latest.value, option.unit))} / ${escapeHtml(latest.date || "-")}</div>
          </div>
          <span class="trend-zoom">${expanded ? "收起" : "放大"}</span>
        </div>
        <canvas data-chart-canvas="${escapeHtml(option.id)}"></canvas>
      </article>
    `;
  }).join("");
  document.querySelectorAll(".trend-card").forEach((card) => {
    card.addEventListener("click", () => {
      const id = card.dataset.chart || "";
      state.expandedChart = state.expandedChart === id ? "" : id;
      renderTrendGrid(state.summary || {});
    });
  });
  requestAnimationFrame(drawTrendGrid);
}

function drawTrendGrid() {
  for (const option of state.chartOptions || []) {
    const canvas = document.querySelector(`[data-chart-canvas="${CSS.escape(option.id)}"]`);
    if (!canvas) continue;
    drawTrendChart(canvas, option, { compact: !state.expandedChart });
  }
}

function drawTrendChart(canvas, option, { compact = false } = {}) {
  const ctx = canvas.getContext("2d");
  if (!option) return;

  const points = (option.points || []).filter((point) => point.value !== null && point.value !== undefined);
  const rect = canvas.getBoundingClientRect();
  const cssWidth = Math.max(220, Math.floor(rect.width));
  const cssHeight = Math.max(compact ? 210 : 460, Math.floor(rect.height));
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const bitmapWidth = Math.floor(cssWidth * dpr);
  const bitmapHeight = Math.floor(cssHeight * dpr);
  if (canvas.width !== bitmapWidth || canvas.height !== bitmapHeight) {
    canvas.width = bitmapWidth;
    canvas.height = bitmapHeight;
  }

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const pad = compact
    ? { left: 66, right: 22, top: 26, bottom: 44 }
    : { left: 84, right: 42, top: 46, bottom: 68 };
  const width = cssWidth - pad.left - pad.right;
  const height = cssHeight - pad.top - pad.bottom;

  ctx.strokeStyle = "#d9e1e7";
  ctx.lineWidth = 1.5;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top);
  ctx.lineTo(pad.left, pad.top + height);
  ctx.lineTo(pad.left + width, pad.top + height);
  ctx.stroke();

  ctx.strokeStyle = "#eef3f5";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i += 1) {
    const y = pad.top + (height / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + width, y);
    ctx.stroke();
  }

  if (!points.length) {
    ctx.fillStyle = "#62707c";
    ctx.font = `${compact ? "600 12px" : "600 16px"} -apple-system, BlinkMacSystemFont, sans-serif`;
    ctx.fillText("暂无可绘制数据", pad.left + 24, pad.top + 80);
    return;
  }

  const values = points.map((point) => Number(point.value));
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min = Math.max(0, min - 1);
    max = max + 1;
  }
  const yFor = (value) => pad.top + height - ((value - min) / (max - min)) * height;
  const xFor = (index) => pad.left + (points.length === 1 ? width / 2 : (index / (points.length - 1)) * width);

  ctx.strokeStyle = "#246fa8";
  ctx.lineWidth = compact ? 3.5 : 4.5;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(Number(point.value));
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(Number(point.value));
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#246fa8";
    ctx.lineWidth = compact ? 3 : 3.5;
    ctx.beginPath();
    ctx.arc(x, y, compact ? 5.5 : 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    const valueText = fmt(point.value, option.unit);
    ctx.font = `760 ${compact ? 12 : 17}px -apple-system, BlinkMacSystemFont, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const textWidth = ctx.measureText(valueText).width;
    const pointOffset = compact ? 18 : 24;
    let labelX = x;
    let labelY = y - pointOffset;
    if (compact) {
      if (index === 0 && points.length > 1) labelX = x + textWidth / 2 + 12;
      if (index === points.length - 1 && points.length > 1) labelX = x - textWidth / 2 - 12;
      labelY = Math.max(pad.top + 16, Math.min(pad.top + height - 16, labelY));
      ctx.fillStyle = "rgba(255,255,255,0.82)";
      const rectX = labelX - textWidth / 2 - 5;
      const rectY = labelY - 10;
      ctx.fillRect(rectX, rectY, textWidth + 10, 20);
      ctx.fillStyle = "#1d2a36";
    } else {
      labelY = Math.max(pad.top + 14, labelY);
      ctx.fillStyle = "#17212b";
    }
    ctx.fillText(valueText, labelX, labelY);
    ctx.fillStyle = "#62707c";
    ctx.font = `650 ${compact ? 12 : 15}px -apple-system, BlinkMacSystemFont, sans-serif`;
    ctx.textBaseline = "alphabetic";
    ctx.fillText(String(point.date || "").slice(5), x, pad.top + height + (compact ? 34 : 40));
  });

  ctx.textAlign = "right";
  ctx.fillStyle = "#62707c";
  ctx.font = `650 ${compact ? 12 : 15}px -apple-system, BlinkMacSystemFont, sans-serif`;
  ctx.fillText(fmt(max, option.unit), pad.left - 10, pad.top + 4);
  ctx.fillText(fmt(min, option.unit), pad.left - 10, pad.top + height + 4);
}

window.addEventListener("resize", () => {
  if (state.summary) drawTrendGrid();
});

function renderAiUsers(summary) {
  const ai = summary.ai_inspection || {};
  const users = ai.users?.length
    ? ai.users
    : (ai.names || []).map((name) => ({ name }));
  $("aiUsersMeta").textContent = `${ai.date || "-"} · ${ai.status || "-"} · ${users.length || 0} 人`;
  $("aiUsers").innerHTML = users.length
    ? users.map((user) => {
      const name = user.name || user["用户姓名"] || "";
      const initials = name.replace(/\(.*?\)/g, "").slice(0, 1) || "-";
      const rate = user.ai_code_local_submit_rate ?? user["AI代码本地提交占比"];
      const title = rate === undefined || rate === null || rate === "" ? name : `${name} · AI提交占比 ${fmt(rate, "%")}`;
      return `
        <span class="ai-user-pill" title="${escapeHtml(title)}">
          <span class="ai-user-avatar">${escapeHtml(initials)}</span>
          <span class="ai-user-name">${escapeHtml(name)}</span>
        </span>
      `;
    }).join("")
    : `<span class="ai-user-pill"><span class="ai-user-avatar">-</span><span>暂无名单</span></span>`;
}

function formatChatTime(value) {
  if (!value) return "";
  const parts = String(value).split(" ");
  return parts.length > 1 ? parts[1].slice(0, 5) : String(value).slice(0, 10);
}

function renderChatSessions() {
  const sessions = state.chatSessions || [];
  $("chatSessions").innerHTML = sessions.length
    ? sessions.map((session) => `
      <button class="chat-session ${session.id === state.currentChatSessionId ? "active" : ""}" type="button" data-session-id="${escapeHtml(session.id)}" title="${escapeHtml(session.title || "新对话")}">
        <span class="chat-session-copy">
          <span class="chat-session-title">${escapeHtml(session.title || "新对话")}</span>
          <span class="chat-session-meta">${escapeHtml(formatChatTime(session.updated_at))} · ${session.message_count ? `${escapeHtml(session.message_count)} 条` : "未开始"}</span>
        </span>
        <span class="chat-session-delete" role="button" tabindex="0" data-delete-session-id="${escapeHtml(session.id)}" aria-label="删除对话" title="删除对话">×</span>
      </button>
    `).join("")
    : `<div class="list-item">暂无历史</div>`;
  document.querySelectorAll(".chat-session").forEach((button) => {
    button.addEventListener("click", async () => {
      await loadChatSession(button.dataset.sessionId || "");
    });
  });
  document.querySelectorAll("[data-delete-session-id]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await deleteChatSession(button.dataset.deleteSessionId || "");
    });
    button.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      event.stopPropagation();
      await deleteChatSession(button.dataset.deleteSessionId || "");
    });
  });
}

function renderMessages(messages) {
  $("messages").innerHTML = "";
  (messages || []).forEach((message) => {
    appendMessage(message.role || "assistant", message.content || "");
  });
}

function appendMessage(role, text) {
  const node = document.createElement("div");
  node.className = `msg ${role}`;
  node.textContent = text;
  $("messages").appendChild(node);
  $("messages").scrollTop = $("messages").scrollHeight;
  return node;
}

async function loadChatSessions() {
  const res = await fetch("/api/chat/sessions");
  if (!res.ok) throw new Error("chat sessions request failed");
  const payload = await res.json();
  state.chatSessions = payload.sessions || [];
  state.currentChatSessionId = payload.active_session_id || state.chatSessions[0]?.id || "";
  renderChatSessions();
  if (state.currentChatSessionId) {
    await loadChatSession(state.currentChatSessionId);
  }
}

async function loadChatSession(sessionId) {
  if (!sessionId) return;
  const res = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`);
  if (!res.ok) return;
  const payload = await res.json();
  state.currentChatSessionId = payload.session?.id || sessionId;
  state.chatSessions = payload.sessions || state.chatSessions;
  renderMessages(payload.session?.messages || []);
  renderChatSessions();
}

async function createChatSession() {
  const res = await fetch("/api/chat/sessions", { method: "POST" });
  if (!res.ok) return;
  const payload = await res.json();
  state.chatSessions = payload.sessions || [];
  state.currentChatSessionId = payload.session?.id || "";
  renderChatSessions();
  renderMessages(payload.session?.messages || []);
}

async function deleteChatSession(sessionId) {
  if (!sessionId) return;
  const ok = await openConfirmModal({
    title: "删除对话",
    description: "删除后将移除这条对话记录。",
    confirmText: "确认删除",
  });
  if (!ok) return;

  try {
    const res = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    if (!res.ok) {
      appendMessage("assistant", "删除对话失败，请刷新页面后重试。");
      return;
    }
    const payload = await res.json();
    state.chatSessions = payload.sessions || [];
    state.currentChatSessionId = payload.active_session_id || payload.session?.id || "";
    renderChatSessions();
    renderMessages(payload.session?.messages || []);
  } catch {
    appendMessage("assistant", "删除对话失败，请检查服务是否正在运行。");
  }
}

async function clearChat() {
  if (!state.currentChatSessionId) {
    await createChatSession();
    return;
  }
  const res = await fetch(`/api/chat/sessions/${encodeURIComponent(state.currentChatSessionId)}/clear`, { method: "POST" });
  if (!res.ok) return;
  const payload = await res.json();
  state.chatSessions = payload.sessions || [];
  renderChatSessions();
  renderMessages(payload.session?.messages || []);
}

async function clearChatHistory() {
  const ok = await openConfirmModal({
    title: "清空历史对话",
    description: "清空后将移除全部历史会话记录，并新建一条空白对话。",
    confirmText: "确认清空",
  });
  if (!ok) return;
  const res = await fetch("/api/chat/sessions/clear-all", { method: "POST" });
  if (!res.ok) return;
  const payload = await res.json();
  state.chatSessions = payload.sessions || [];
  state.currentChatSessionId = payload.session?.id || "";
  renderChatSessions();
  renderMessages(payload.session?.messages || []);
}

async function loadJobs() {
  const res = await fetch("/api/jobs");
  if (!res.ok) return;
  const payload = await res.json();
  renderJobs(payload.jobs || []);
}

async function loadAgentTrace() {
  const res = await fetch("/api/tools/audit");
  if (!res.ok) return;
  const payload = await res.json();
  state.auditEvents = payload.events || [];
  renderAgentTrace(state.auditEvents);
}

async function clearAgentTrace() {
  const ok = await openConfirmModal({
    title: "清空 Agent 轨迹",
    description: "清空后将移除当前工具调用、确认门和执行审计记录。",
    confirmText: "确认清空",
  });
  if (!ok) return;
  const res = await fetch("/api/tools/audit/clear", { method: "POST" });
  if (!res.ok) {
    appendMessage("assistant", "清空 Agent 轨迹失败，请稍后重试。");
    return;
  }
  state.auditEvents = [];
  renderAgentTrace([]);
}

async function clearJobs() {
  const res = await fetch("/api/jobs/clear", { method: "POST" });
  if (!res.ok) return;
  renderJobs([]);
  appendMessage("assistant", "任务记录已清空。");
}

async function runAction(action, options = {}) {
  if (!action) return;
  const actionMeta = findAction(action) || {};
  const triggerButton = options.button || null;
  const originalText = triggerButton?.textContent || "";
  const setButtonText = (text, disabled = true) => {
    if (!triggerButton) return;
    triggerButton.textContent = text;
    triggerButton.disabled = disabled;
  };
  const restoreButton = () => {
    if (!triggerButton) return;
    triggerButton.textContent = originalText;
    triggerButton.disabled = actionMeta.id ? !actionCanRun(actionMeta) : false;
  };
  if (actionMeta.id && !actionCanRun(actionMeta)) {
    setButtonText("不可执行", true);
    appendMessage("assistant", actionUnavailableText(actionMeta));
    window.setTimeout(restoreButton, 1600);
    return;
  }
  const confirmPhrase = actionMeta.confirm_phrase || "";
  let message = "";
  const needsConfirm = options.forceConfirm || actionMeta.risk === "write";
  if (needsConfirm) {
    const ok = await openConfirmModal({
      title: options.confirmTitle || actionMeta.title || "确认执行",
      description: actionMeta.risk === "write"
        ? `${actionMeta.title || "该动作"}会修改线上数据，确认后才会继续执行。`
        : `确认后将开始执行${options.confirmTitle || actionMeta.title || "该操作"}。`,
      confirmText: "确认执行",
    });
    if (!ok) {
      appendMessage("assistant", "已取消执行。");
      return;
    }
    if (actionMeta.risk === "write") {
      message = confirmPhrase;
    }
  }
  setButtonText("提交中...", true);
  try {
    const res = await fetch("/api/actions/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, message }),
    });
    const payload = await res.json();
    appendMessage("assistant", payload.answer || payload.message || "动作已提交。");
    await loadJobs();
    await loadAgentTrace();
    if (payload.job) {
      setButtonText("已提交", true);
      ensureJobsPolling();
    } else if (payload.error) {
      setButtonText("未提交", true);
    } else {
      setButtonText("已处理", true);
    }
  } catch (error) {
    appendMessage("assistant", "动作提交失败，请检查服务是否正在运行。");
    setButtonText("提交失败", true);
  } finally {
    window.setTimeout(restoreButton, 1800);
  }
}

async function runToolbarPrompt(button) {
  const prompt = button.dataset.prompt || "";
  if (!prompt) return;
  const confirmPhrase = button.dataset.confirmPhrase || "";
  const ok = await openConfirmModal({
    title: button.dataset.confirmTitle || button.textContent.trim() || "确认执行",
    description: "确认后会切换到 AI 对话页，并立即开始对应巡检或问答流程。",
    confirmText: "确认执行",
  });
  if (!ok) return;
  switchView("chat");
  const confirmedPrompt = confirmPhrase && !prompt.includes(confirmPhrase)
    ? `${prompt}，${confirmPhrase}`
    : prompt;
  await sendChat(confirmedPrompt);
}

function renderJobs(jobs) {
  $("jobs").innerHTML = jobs.length
    ? jobs.map((job) => {
      const logs = (job.logs || []).slice(-8).join("\n");
      return `
        <article class="job-card">
          <div class="job-title">
            <span>${escapeHtml(job.title || job.action)}</span>
            <span class="${statusClass(job.status)}">${escapeHtml(statusLabel(job.status))}</span>
          </div>
          <div class="job-meta">步骤 ${escapeHtml(job.current_step ?? 0)} / ${escapeHtml(job.total_steps ?? 0)} · ${escapeHtml(job.updated_at || job.created_at || "-")}</div>
          ${logs ? `<pre class="job-log">${escapeHtml(logs)}</pre>` : ""}
        </article>
      `;
    }).join("")
    : `<div class="list-item">暂无任务</div>`;
}

function toolEventTone(eventName = "", jobStatus = "") {
  if (eventName.includes("confirmation_required")) return "blocked";
  if (jobStatus === "partial") return "blocked";
  if (eventName.includes("rejected") || jobStatus === "failed" || jobStatus === "timeout") return "failed";
  if (eventName.includes("finished") || jobStatus === "success") return "success";
  return "running";
}

function toolEventLabel(event = {}) {
  const eventName = event.event || "";
  const status = event.job?.status || event.tool_result?.job?.status || event.tool_result?.status || "";
  if (eventName === "planner_completed") return "Planner";
  if (eventName === "evaluator_completed") return "Evaluator";
  if (eventName.includes("confirmation_required")) return "确认门";
  if (eventName.includes("rejected")) return "已拒绝";
  if (eventName.includes("queued")) return "已入队";
  if (eventName.includes("finished") && status === "partial") return "部分完成";
  if (eventName.includes("finished")) return status === "success" ? "已完成" : status || "已结束";
  return eventName || "事件";
}

function compactPayload(value) {
  const text = JSON.stringify(value || {}, null, 2);
  return text.length > 1800 ? `${text.slice(0, 1800)}\n...` : text;
}

function renderAgentTrace(events) {
  const latest = [...(events || [])].reverse().slice(0, 30);
  $("agentTrace").innerHTML = latest.length
    ? latest.map((event) => {
      const toolCall = event.tool_call || event.tool_result?.tool_call || {};
      const action = event.action || event.tool_result?.action || "";
      const job = event.job || event.tool_result?.job || {};
      const source = toolCall.source || "-";
      const subject = event.event === "planner_completed"
        ? (event.plan?.plan_type || "规划完成")
        : event.event === "evaluator_completed"
          ? (event.evaluation?.status || "评估完成")
          : (toolCall.name || "-");
      const tone = toolEventTone(event.event, job.status || event.tool_result?.status || "");
      const payload = {
        tool_call: toolCall,
        tool_result: event.tool_result,
        job: event.job,
        plan: event.plan,
        evaluation: event.evaluation,
        required_phrase: event.required_phrase,
      };
      return `
        <article class="agent-trace-item ${escapeHtml(tone)}">
          <div class="agent-trace-stamp">
            <span>${escapeHtml(String(event.time || "-").slice(5, 16))}</span>
          </div>
          <div class="agent-trace-body">
            <div class="agent-trace-title">
              <span class="trace-badge">${escapeHtml(toolEventLabel(event))}</span>
              <strong>${escapeHtml(action ? actionLabel(action) : toolEventLabel(event))}</strong>
              <span>${escapeHtml(subject)}</span>
            </div>
            <div class="agent-trace-meta">
              <span>来源：${escapeHtml(source)}</span>
              <span>事件：${escapeHtml(event.event || "-")}</span>
              ${job.id ? `<span>job：${escapeHtml(job.id)}</span>` : ""}
            </div>
            <details class="agent-trace-detail">
              <summary>参数 / 结果</summary>
              <pre>${escapeHtml(compactPayload(payload))}</pre>
            </details>
          </div>
        </article>
      `;
    }).join("")
    : `<div class="list-item">暂无 Agent 工具调用轨迹</div>`;
}

function renderFreshnessPanel(summary) {
  const items = summary.freshness?.fixed_cycle_reports || [];
  const panel = $("freshnessPanel");
  if (!items.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  panel.innerHTML = `
    <div class="freshness-head">
      <div>
        <h2>固定周期数据</h2>
        <p>周四/周五模块只展示本周有效窗口内的数据</p>
      </div>
    </div>
    <div class="freshness-grid">
      ${items.map((item) => `
        <article class="freshness-card freshness-${escapeHtml(item.state || "unknown")}">
          <div class="freshness-title-row">
            <strong>${escapeHtml(item.title || "-")}</strong>
            <span>${escapeHtml(item.label || "-")}</span>
          </div>
          <p>${escapeHtml(item.message || "")}</p>
          <div class="freshness-meta">
            <span>执行日：${escapeHtml(item.expected_date || "-")}</span>
            <span>数据日：${escapeHtml(item.source_date || "-")}</span>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function ensureJobsPolling() {
  if (state.jobsTimer) return;
  state.jobsTimer = setInterval(async () => {
    await loadJobs();
    await loadAgentTrace();
  }, 3000);
}

function parseStreamEvent(block) {
  const event = { type: "message", data: "" };
  block.split("\n").forEach((line) => {
    if (line.startsWith("event:")) {
      event.type = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      event.data += line.slice(5).trim();
    }
  });
  if (!event.data) return null;
  try {
    return { type: event.type, payload: JSON.parse(event.data) };
  } catch {
    return null;
  }
}

async function sendChat(message) {
  if (!state.currentChatSessionId) {
    await createChatSession();
  }
  appendMessage("user", message);
  const assistantNode = appendMessage("assistant", "");
  const settings = formAiSettings();
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: state.currentChatSessionId,
      ai: { model: settings.model },
    }),
  });

  if (!res.ok || !res.body) {
    assistantNode.textContent = "对话请求失败。";
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const event = parseStreamEvent(block);
      if (!event) continue;
      if (event.type === "meta") {
        state.currentChatSessionId = event.payload.session_id || state.currentChatSessionId;
        if (event.payload.job || event.payload.jobs?.length || event.payload.action !== "none") {
          await loadJobs();
          await loadAgentTrace();
          ensureJobsPolling();
        }
      } else if (event.type === "delta") {
        assistantNode.textContent += event.payload.text || "";
        $("messages").scrollTop = $("messages").scrollHeight;
      } else if (event.type === "done") {
        donePayload = event.payload;
      }
    }
  }

  const tailEvent = parseStreamEvent(buffer.trim());
  if (tailEvent?.type === "done") {
    donePayload = tailEvent.payload;
  }

  if (donePayload) {
    state.currentChatSessionId = donePayload.session_id || state.currentChatSessionId;
    if (donePayload.answer && !assistantNode.textContent) {
      assistantNode.textContent = donePayload.answer;
    }
    if (donePayload.sessions) {
      state.chatSessions = donePayload.sessions;
      renderChatSessions();
    }
    if (donePayload.job) {
      await loadJobs();
      await loadAgentTrace();
      ensureJobsPolling();
    } else if (donePayload.tool_call || donePayload.tool_calls?.length) {
      await loadAgentTrace();
    }
  } else if (!assistantNode.textContent) {
    assistantNode.textContent = "没有返回内容";
  }
}

function render() {
  const summary = state.summary || {};
  renderHeader(summary);
  renderFreshnessPanel(summary);
  renderOverview(summary);
  renderTrendGrid(summary);
  renderAiUsers(summary);
}

function switchView(view) {
  const nextView = view === "chat" ? "chat" : "dashboard";
  document.querySelectorAll("[data-view-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewTab === nextView);
  });
  document.querySelectorAll(".dashboard-view").forEach((node) => {
    node.hidden = nextView !== "dashboard";
  });
  $("chatView").hidden = nextView !== "chat";
}

$("refreshBtn").addEventListener("click", async () => {
  const ok = await openConfirmModal({
    title: $("refreshBtn").dataset.confirmTitle || "刷新数据",
    description: "确认后会重新读取本地巡检数据，并刷新当前看板内容。",
    confirmText: "确认刷新",
  });
  if (!ok) return;
  await loadSummary();
});
$("syncStaticBtn").addEventListener("click", async () => {
  await syncPublicSite();
});
$("modelSelect").addEventListener("change", async () => {
  await saveSettings();
});
$("refreshJobsBtn").addEventListener("click", loadJobs);
$("refreshAgentTraceBtn").addEventListener("click", loadAgentTrace);
$("clearAgentTraceBtn").addEventListener("click", clearAgentTrace);
$("clearJobsBtn").addEventListener("click", clearJobs);
$("clearChatBtn").addEventListener("click", async () => {
  await clearChat();
});
$("newChatBtn").addEventListener("click", async () => {
  await createChatSession();
});
$("clearHistoryBtn").addEventListener("click", async () => {
  await clearChatHistory();
});
$("runMoreActionBtn").addEventListener("click", async () => {
  await runAction($("moreActionSelect").value, { button: $("runMoreActionBtn") });
});
document.querySelectorAll("[data-view-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    switchView(button.dataset.viewTab || "dashboard");
  });
});
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.closest(".toolbar")) {
      await runToolbarPrompt(button);
      return;
    }
    switchView("chat");
    await sendChat(button.dataset.prompt || "");
  });
});
$("confirmCancelBtn").addEventListener("click", () => closeConfirmModal(false));
$("confirmAcceptBtn").addEventListener("click", () => closeConfirmModal(true));
$("confirmBackdrop").addEventListener("click", () => closeConfirmModal(false));
$("imagePreviewCloseBtn").addEventListener("click", closeImagePreview);
$("imagePreviewBackdrop").addEventListener("click", closeImagePreview);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("confirmModal").hidden) {
    closeConfirmModal(false);
  }
  if (event.key === "Escape" && !$("imagePreviewModal").hidden) {
    closeImagePreview();
  }
});
$("trendResetBtn").addEventListener("click", () => {
  state.expandedChart = "";
  renderTrendGrid(state.summary || {});
});
$("chatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("chatInput");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  await sendChat(message);
});
$("chatInput").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  const input = $("chatInput");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  await sendChat(message);
});

renderSettings();
loadAiConfig().catch(() => renderSettings(defaultSettings));
loadChatSessions().catch((error) => appendMessage("assistant", `对话历史加载失败：${error.message}`));
loadActions().catch((error) => appendMessage("assistant", `功能加载失败：${error.message}`));
loadJobs();
loadAgentTrace();
loadSummary().catch((error) => {
  appendMessage("assistant", `加载失败：${error.message}`);
});
