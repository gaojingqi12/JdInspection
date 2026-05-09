const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";

const labels = {
  delay_test_rate_okr: "延期提测率",
  delay_online_rate: "延期上线率",
  technical_refactor_working_hours_rate: "技术改造工时占比",
  biweekly_delivery_rate: "双周交付率",
  delayed_test_requirements: "延期提测需求数",
  delayed_online_requirements: "延期上线需求数",
  ai_non_deep_users: "AI 深度用户为否",
  continuous_delivery_team_space_online_requirement_rate: "持续交付占比",
};

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmt(value, unit = "") {
  if (value === null || value === undefined || value === "") return "-";
  const shown = typeof value === "number" && !Number.isInteger(value)
    ? String(Number(value.toFixed(2))).replace(/\.0$/, "")
    : String(value);
  return unit === "%" ? `${shown}%` : shown;
}

function displayUnit(unit = "") {
  return ({ count: "个", hour: "人天", "人": "人" })[unit] || unit;
}

function renderHeader(summary) {
  $("department").textContent = summary.display_domain || summary.department_c3 || "-";
  $("range").textContent = `${summary.time_range?.start_date || "-"} ~ ${summary.time_range?.end_date || "-"}`;
  $("publicLoadedAt").textContent = `加载 ${summary.loaded_at || "-"}`;
}

function renderOverview(summary) {
  const cards = summary.overview || [];
  $("overview").innerHTML = cards.map((card) => `
    <article class="metric-card metric-${escapeHtml(card.indicator_type || "default")}">
      <div class="metric-topline">
        <span class="metric-caption">${escapeHtml(card.caption || "指标")}</span>
      </div>
      <div class="metric-label">${escapeHtml(card.label)}</div>
      <div class="metric-value">${escapeHtml(card.display_value)}${card.unit && card.unit !== "%" ? `<span class="muted"> ${escapeHtml(displayUnit(card.unit))}</span>` : ""}</div>
      <div class="metric-foot">
        <span>${escapeHtml(card.date || "-")}</span>
        <span>${escapeHtml(card.title || "")}</span>
      </div>
    </article>
  `).join("");
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
  const options = buildChartOptions(summary);
  $("trendGrid").innerHTML = options.map((option) => {
    const latest = latestNonNull(option.points || []);
    return `
      <article class="trend-card">
        <div class="trend-card-head">
          <div>
            <div class="trend-title">${escapeHtml(option.title)}</div>
            <div class="trend-meta">最新值 ${escapeHtml(fmt(latest.value, option.unit))} / ${escapeHtml(latest.date || "-")}</div>
          </div>
        </div>
        <canvas data-board-chart="${escapeHtml(option.id)}"></canvas>
      </article>
    `;
  }).join("");

  requestAnimationFrame(() => {
    options.forEach((option) => {
      const canvas = document.querySelector(`[data-board-chart="${CSS.escape(option.id)}"]`);
      if (canvas) drawTrendChart(canvas, option);
    });
  });
}

function drawTrendChart(canvas, option) {
  const ctx = canvas.getContext("2d");
  const points = (option.points || []).filter((point) => point.value !== null && point.value !== undefined);
  const rect = canvas.getBoundingClientRect();
  const cssWidth = Math.max(220, Math.floor(rect.width));
  const cssHeight = Math.max(130, Math.floor(rect.height));
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const bitmapWidth = Math.floor(cssWidth * dpr);
  const bitmapHeight = Math.floor(cssHeight * dpr);
  if (canvas.width !== bitmapWidth || canvas.height !== bitmapHeight) {
    canvas.width = bitmapWidth;
    canvas.height = bitmapHeight;
  }

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const pad = { left: 58, right: 16, top: 18, bottom: 34 };
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
    ctx.font = "600 12px -apple-system, BlinkMacSystemFont, sans-serif";
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
  ctx.lineWidth = 3;
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
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(x, y, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    const valueText = fmt(point.value, option.unit);
    ctx.font = "700 10px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const textWidth = ctx.measureText(valueText).width;
    let labelX = x;
    let labelY = y - 14;
    if (index === 0 && points.length > 1) labelX = x + textWidth / 2 + 10;
    if (index === points.length - 1 && points.length > 1) labelX = x - textWidth / 2 - 10;
    labelY = Math.max(pad.top + 12, Math.min(pad.top + height - 12, labelY));
    ctx.fillStyle = "rgba(255,255,255,0.78)";
    ctx.fillRect(labelX - textWidth / 2 - 4, labelY - 8, textWidth + 8, 16);
    ctx.fillStyle = "#1d2a36";
    ctx.fillText(valueText, labelX, labelY);

    ctx.fillStyle = "#62707c";
    ctx.font = "600 10px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(String(point.date || "").slice(5), x, pad.top + height + 30);
  });

  ctx.textAlign = "right";
  ctx.fillStyle = "#62707c";
  ctx.font = "600 10px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.fillText(fmt(max, option.unit), pad.left - 10, pad.top + 4);
  ctx.fillText(fmt(min, option.unit), pad.left - 10, pad.top + height + 4);
}

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

async function loadSummary() {
  const res = await fetch(`${API_BASE}/api/summary`);
  if (!res.ok) throw new Error("summary request failed");
  const summary = await res.json();
  renderHeader(summary);
  renderOverview(summary);
  renderTrendGrid(summary);
  renderAiUsers(summary);
}

window.addEventListener("resize", () => {
  loadSummary().catch(() => {});
});

loadSummary().catch((error) => {
  $("publicLoadedAt").textContent = `加载失败：${error.message}`;
});
