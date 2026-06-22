const STATUS_LABELS = {
  new: "Новый",
  contacted: "Связались",
  qualified: "Квалифицирован",
  lost: "Потерян",
};

const SOURCE_LABELS = {
  landing: "Лендинг",
  telegram: "Telegram",
  instagram: "Instagram",
  facebook: "Facebook",
  email: "Email",
  partner: "Партнёр",
  website: "Сайт",
  whatsapp: "WhatsApp",
};

function formatDate(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatValue(value) {
  return value && String(value).trim() ? value : "—";
}

function formatSource(source) {
  if (!source) return "—";
  return SOURCE_LABELS[source] || source;
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3000);
}

function showError(message) {
  const el = document.getElementById("error");
  el.textContent = message;
  el.hidden = !message;
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const detail = data.error || data.detail || "Ошибка запроса";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return data;
}

function renderStats(leads) {
  document.getElementById("stat-total").textContent = leads.length;

  const byStatus = leads.reduce((acc, lead) => {
    acc[lead.status] = (acc[lead.status] || 0) + 1;
    return acc;
  }, {});

  document.getElementById("stat-new").textContent = byStatus.new || 0;
  document.getElementById("stat-qualified").textContent = byStatus.qualified || 0;

  const sources = new Set(leads.map((l) => l.source).filter(Boolean));
  document.getElementById("stat-sources").textContent = sources.size;
}

function renderLeadCard(lead) {
  const card = document.createElement("article");
  card.className = "lead-card";
  card.dataset.id = lead.id;

  card.innerHTML = `
    <div class="lead-card-header">
      <div>
        <div class="lead-id">#${lead.id}</div>
        <h3>${escapeHtml(lead.name)}</h3>
      </div>
      <span class="badge badge-${lead.status}">${STATUS_LABELS[lead.status] || lead.status}</span>
    </div>
    <dl class="lead-meta">
      <div><dt>Контакт</dt><dd>${escapeHtml(formatValue(lead.contact || lead.phone || lead.email))}</dd></div>
      <div><dt>Email</dt><dd>${escapeHtml(formatValue(lead.email))}</dd></div>
      <div><dt>Телефон</dt><dd>${escapeHtml(formatValue(lead.phone))}</dd></div>
      <div><dt>Источник</dt><dd>${escapeHtml(formatSource(lead.source))}</dd></div>
      <div><dt>Комментарий</dt><dd>${escapeHtml(formatValue(lead.comment || lead.notes))}</dd></div>
      <div><dt>Создана</dt><dd>${formatDate(lead.created_at)}</dd></div>
      <div><dt>Обновлена</dt><dd>${formatDate(lead.updated_at)}</dd></div>
    </dl>
    <div class="lead-actions">
      <select class="status-select" aria-label="Статус">
        ${Object.entries(STATUS_LABELS)
          .map(
            ([value, label]) =>
              `<option value="${value}" ${lead.status === value ? "selected" : ""}>${label}</option>`
          )
          .join("")}
      </select>
      <button class="btn btn-sm btn-danger delete-btn" type="button">Удалить</button>
    </div>
  `;

  card.querySelector(".status-select").addEventListener("change", async (e) => {
    try {
      await api(`/leads/${lead.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: e.target.value }),
      });
      showToast(`Статус #${lead.id} обновлён`);
      await refreshData();
    } catch (err) {
      showError(err.message);
      e.target.value = lead.status;
    }
  });

  card.querySelector(".delete-btn").addEventListener("click", async () => {
    if (!confirm(`Удалить заявку #${lead.id} (${lead.name})?`)) return;
    try {
      await api(`/leads/${lead.id}`, { method: "DELETE" });
      showToast(`Заявка #${lead.id} удалена`);
      await refreshData();
    } catch (err) {
      showError(err.message);
    }
  });

  return card;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

const STATUS_CLASS = {
  Новый: "status-new",
  Связались: "status-contacted",
  Квалифицирован: "status-qualified",
  Потерян: "status-lost",
};

function renderBarChart(container, items, fillClass = "") {
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = '<div class="empty" style="padding: 1rem;">Нет данных</div>';
    return;
  }

  const maxCount = Math.max(...items.map((item) => item.count), 1);

  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    const width = Math.round((item.count / maxCount) * 100);
    const barClass = fillClass || STATUS_CLASS[item.label] || "";
    row.innerHTML = `
      <span class="bar-label" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>
      <div class="bar-track"><div class="bar-fill ${barClass}" style="width: ${width}%"></div></div>
      <span class="bar-value">${item.count}</span>
    `;
    container.appendChild(row);
  });
}

function switchView(view) {
  const leadsView = document.getElementById("leads-view");
  const dashboardView = document.getElementById("dashboard-view");
  const tabLeads = document.getElementById("tab-leads");
  const tabDashboard = document.getElementById("tab-dashboard");

  const isDashboard = view === "dashboard";
  leadsView.hidden = isDashboard;
  dashboardView.hidden = !isDashboard;
  tabLeads.classList.toggle("active", !isDashboard);
  tabDashboard.classList.toggle("active", isDashboard);

  if (isDashboard) {
    loadDashboard();
  }
}

async function loadDashboard() {
  const containers = {
    date: document.getElementById("chart-by-date"),
    source: document.getElementById("chart-by-source"),
    status: document.getElementById("chart-by-status"),
  };

  Object.values(containers).forEach(
    (container) => (container.innerHTML = '<div class="loading" style="padding: 1rem;">Загрузка...</div>')
  );

  try {
    const data = await api("/api/dashboard");
    document.getElementById("dashboard-summary").textContent = `Всего заявок: ${data.total}`;
    renderBarChart(containers.date, data.by_date);
    renderBarChart(containers.source, data.by_source, "source");
    renderBarChart(containers.status, data.by_status);
  } catch (err) {
    Object.values(containers).forEach((container) => (container.innerHTML = ""));
    showError(err.message);
  }
}

async function refreshData() {
  await loadLeads();
  if (!document.getElementById("dashboard-view").hidden) {
    await loadDashboard();
  }
}

async function loadLeads() {
  const list = document.getElementById("leads-list");
  const filter = document.getElementById("status-filter").value;
  const query = document.getElementById("search-query").value.trim();
  const searchBy = document.getElementById("search-by").value;

  list.innerHTML = '<div class="loading">Загрузка заявок...</div>';
  showError("");

  try {
    const params = new URLSearchParams({ limit: "500" });
    if (filter) params.set("status", filter);
    if (query) {
      params.set("q", query);
      params.set("search_by", searchBy);
    }
    const leads = await api(`/leads?${params.toString()}`);

    renderStats(leads);
    list.innerHTML = "";

    if (!leads.length) {
      list.innerHTML = query
        ? '<div class="empty">Ничего не найдено</div>'
        : '<div class="empty">Заявок пока нет</div>';
      return;
    }

    leads.forEach((lead) => list.appendChild(renderLeadCard(lead)));
  } catch (err) {
    list.innerHTML = "";
    showError(err.message);
  }
}

document.getElementById("lead-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;

  const payload = {
    name: form.name.value.trim(),
    email: form.email.value.trim() || null,
    phone: form.phone.value.trim() || null,
    source: form.source.value.trim() || null,
    notes: form.notes.value.trim() || null,
  };

  try {
    await api("/leads", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    form.reset();
    showToast("Заявка успешно создана");
    await refreshData();
  } catch (err) {
    showError(err.message);
  }
});

document.getElementById("status-filter").addEventListener("change", loadLeads);
document.getElementById("refresh-btn").addEventListener("click", loadLeads);
document.getElementById("dashboard-refresh-btn").addEventListener("click", loadDashboard);

document.querySelectorAll(".view-tab").forEach((tab) => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});

document.getElementById("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  loadLeads();
});

document.getElementById("search-reset").addEventListener("click", () => {
  document.getElementById("search-query").value = "";
  document.getElementById("search-by").value = "name";
  loadLeads();
});

document.getElementById("import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const fileInput = form.file;
  const resultEl = document.getElementById("import-result");

  if (!fileInput.files.length) {
    showError("Выберите файл .xlsx");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  showError("");

  try {
    const response = await fetch("/leads/import", {
      method: "POST",
      body: formData,
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.error || data.detail || "Ошибка импорта");
    }

    let message = `Импортировано: ${data.created}`;
    if (data.skipped) {
      message += `, пропущено: ${data.skipped}`;
    }

    resultEl.hidden = false;
    if (data.errors && data.errors.length) {
      resultEl.innerHTML = `
        <div>${message}</div>
        <ul>${data.errors.map((err) => `<li>${escapeHtml(err)}</li>`).join("")}</ul>
      `;
    } else {
      resultEl.textContent = message;
    }

    showToast(message);
    form.reset();
    await refreshData();
  } catch (err) {
    resultEl.hidden = true;
    showError(err.message);
  }
});

loadLeads();
