/* ==========================================================================
   SAG for People - HR CRM Portal Client Logic
   ========================================================================== */

const API_BASE = "";

let state = {
  token: localStorage.getItem("sag_jwt_token") || null,
  currentUser: null,
  factories: [],
  departments: [],
  roles: [],
  recruiters: [],
  requisitions: [],
  candidates: [],
  activeTab: "requisitions"
};

// Debounce timer for search
let searchTimer = null;

// ==========================================================================
// Theme Switcher (Light / Dark Background Toggle)
// ==========================================================================
function initTheme() {
  const savedTheme = localStorage.getItem("sag_theme") || "light";
  applyTheme(savedTheme);
}

function toggleTheme() {
  const isLight = document.body.classList.contains("theme-light");
  const newTheme = isLight ? "dark" : "light";
  applyTheme(newTheme);
  localStorage.setItem("sag_theme", newTheme);
  showToast(newTheme === "light" ? "Включен белый фон" : "Включен темный фон", "info");
}

function applyTheme(theme) {
  const buttons = document.querySelectorAll(".theme-btn-global");
  if (theme === "light") {
    document.body.classList.add("theme-light");
    buttons.forEach(btn => {
      const icon = btn.querySelector(".theme-icon");
      const text = btn.querySelector(".theme-text");
      if (icon) icon.textContent = "🌙";
      if (text) text.textContent = "Темный фон";
    });
  } else {
    document.body.classList.remove("theme-light");
    buttons.forEach(btn => {
      const icon = btn.querySelector(".theme-icon");
      const text = btn.querySelector(".theme-text");
      if (icon) icon.textContent = "☀️";
      if (text) text.textContent = "Белый фон";
    });
  }
}

// ==========================================================================
function initTelegramWebApp() {
  if (window.Telegram && window.Telegram.WebApp) {
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
  }
}

// Initialization & Auth
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initTelegramWebApp();
  document.getElementById("loginForm").addEventListener("submit", handleLoginSubmit);
  checkAuth();
});

async function apiRequest(url, options = {}) {
  const headers = options.headers || {};
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  options.headers = headers;

  try {
    const res = await fetch(API_BASE + url, options);
    if (res.status === 401) {
      logout();
      throw new Error("Сессия истекла. Пожалуйста, войдите снова.");
    }
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Ошибка сервера: ${res.status}`);
    }
    const contentType = res.headers.get("content-type");
    if (contentType && contentType.includes("application/json")) {
      return await res.json();
    }
    return res;
  } catch (err) {
    showToast(err.message, "error");
    throw err;
  }
}

async function checkAuth() {
  if (!state.token) {
    showLoginView();
    return;
  }
  try {
    const user = await apiRequest("/api/auth/me");
    state.currentUser = user;
    showMainAppView();
    await loadInitialReferences();
    switchTab("requisitions");
  } catch (err) {
    showLoginView();
  }
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const email = document.getElementById("loginEmail").value.trim();
  const pin = document.getElementById("loginPin").value.trim();
  const errDiv = document.getElementById("loginError");
  errDiv.style.display = "none";

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username_email: email, pin: pin })
    });
    const data = await res.json();
    if (!res.ok) {
      errDiv.textContent = data.detail || "Ошибка авторизации";
      errDiv.style.display = "flex";
      return;
    }
    state.token = data.access_token;
    state.currentUser = data.user;
    localStorage.setItem("sag_jwt_token", state.token);
    showMainAppView();
    await loadInitialReferences();
    switchTab("requisitions");
    showToast(`Добро пожаловать, ${state.currentUser.first_name}!`, "success");
  } catch (err) {
    errDiv.textContent = "Ошибка соединения с сервером";
    errDiv.style.display = "flex";
  }
}

function quickLogin(email) {
  document.getElementById("loginEmail").value = email;
  document.getElementById("loginPin").value = "1234";
  document.getElementById("loginForm").dispatchEvent(new Event("submit"));
}

function logout() {
  state.token = null;
  state.currentUser = null;
  localStorage.removeItem("sag_jwt_token");
  showLoginView();
  showToast("Вы успешно вышли из системы", "info");
}

function showLoginView() {
  document.getElementById("loginView").style.display = "block";
  document.getElementById("mainAppView").style.display = "none";
  const mobileNav = document.querySelector(".mobile-bottom-nav");
  if (mobileNav) mobileNav.style.display = "none";
}

function showMainAppView() {
  document.getElementById("loginView").style.display = "none";
  document.getElementById("mainAppView").style.display = "flex";
  const mobileNav = document.querySelector(".mobile-bottom-nav");
  if (mobileNav) mobileNav.style.display = "flex";

  // Update profile in header
  const user = state.currentUser;
  document.getElementById("userName").textContent = `${user.first_name} ${user.last_name}`;
  document.getElementById("userRoleBadge").textContent = user.role_names.join(", ");

  // Show/Hide Admin Tab
  const isAdmin = user.roles.includes("admin");
  document.getElementById("tabNavAdmin").style.display = isAdmin ? "flex" : "none";
  const mobileAdmin = document.getElementById("mobileTabAdmin");
  if (mobileAdmin) mobileAdmin.style.display = isAdmin ? "flex" : "none";
}

// ==========================================================================
// Reference Data & Select Population
// ==========================================================================
async function loadInitialReferences() {
  try {
    const [factories, departments, roles, recruiters] = await Promise.all([
      apiRequest("/api/factories"),
      apiRequest("/api/departments"),
      apiRequest("/api/roles"),
      apiRequest("/api/recruiters")
    ]);
    state.factories = factories;
    state.departments = departments;
    state.roles = roles;
    state.recruiters = recruiters;

    populateSelects();
  } catch (err) {
    console.error("Failed loading references", err);
  }
}

function populateSelects() {
  // Requisitions filters & modal
  const reqFilterDept = document.getElementById("reqFilterDept");
  const candFilterDept = document.getElementById("candFilterDept");
  const reqDeptInput = document.getElementById("reqDeptInput");
  const candDeptInput = document.getElementById("candDeptInput");
  const userDept = document.getElementById("userDept");

  let deptOpts = '<option value="">Все отделы / цеха</option>';
  let deptInputOpts = '<option value="">Выберите подразделение</option>';

  state.departments.forEach(d => {
    deptOpts += `<option value="${d.id}">${d.name}</option>`;
    deptInputOpts += `<option value="${d.id}">${d.name}</option>`;
  });

  if (reqFilterDept) reqFilterDept.innerHTML = deptOpts;
  if (candFilterDept) candFilterDept.innerHTML = deptOpts;
  if (reqDeptInput) reqDeptInput.innerHTML = deptInputOpts;
  if (candDeptInput) candDeptInput.innerHTML = deptInputOpts;
  if (userDept) userDept.innerHTML = deptInputOpts;

  // Recruiters selects
  const reqRecruiterInput = document.getElementById("reqRecruiterInput");
  const candRecruiterInput = document.getElementById("candRecruiterInput");
  let recOpts = '<option value="">Не назначен</option>';
  state.recruiters.forEach(r => {
    recOpts += `<option value="${r.id}">${r.first_name} ${r.last_name}</option>`;
  });
  if (reqRecruiterInput) reqRecruiterInput.innerHTML = recOpts;
  if (candRecruiterInput) candRecruiterInput.innerHTML = recOpts;

  // Factories select
  const userFactory = document.getElementById("userFactory");
  let factOpts = '';
  state.factories.forEach(f => {
    factOpts += `<option value="${f.id}">${f.name}</option>`;
  });
  if (userFactory) userFactory.innerHTML = factOpts;
}

// ==========================================================================
// Tabs & Views Navigation
// ==========================================================================
function switchTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll(".nav-tab, .mobile-nav-item").forEach(t => {
    t.classList.toggle("active", t.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-content").forEach(c => {
    c.classList.toggle("active", c.id === `tab-${tabName}`);
  });

  if (tabName === "requisitions") loadRequisitions();
  if (tabName === "candidates") loadCandidates();
  if (tabName === "executive") loadExecutiveAnalytics();
  if (tabName === "recruiters") loadRecruiterAnalytics();
  if (tabName === "admin") loadAdminUsers();
}

// ==========================================================================
// TAB 1: Requisitions Management
// ==========================================================================
async function loadRequisitions() {
  const deptId = document.getElementById("reqFilterDept").value;
  const statusFilter = document.getElementById("reqFilterStatus").value;

  let url = `/api/requisitions?1=1`;
  if (deptId) url += `&department_id=${deptId}`;
  if (statusFilter) url += `&status_filter=${encodeURIComponent(statusFilter)}`;

  try {
    const data = await apiRequest(url);
    state.requisitions = data;
    renderRequisitionsTable(data);
    updateCandidateReqSelect(data);
  } catch (err) {
    console.error(err);
  }
}

function renderRequisitionsTable(reqs) {
  const tbody = document.getElementById("requisitionsTableBody");
  if (!reqs || reqs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--text-muted); padding:2rem;">Заявки не найдены</td></tr>`;
    return;
  }

  const isDirectorOrAdmin = state.currentUser.roles.some(r => ["admin", "director"].includes(r));
  const isManager = state.currentUser.roles.includes("manager");

  tbody.innerHTML = reqs.map(r => {
    let badgeClass = "badge-new";
    if (r.status.includes("Утверждена")) badgeClass = "badge-working";
    if (r.status.includes("Выполнена")) badgeClass = "badge-closed";
    if (r.status.includes("Отклонена")) badgeClass = "badge-rejected";

    const canEdit = isDirectorOrAdmin || (isManager && r.status === "Новая заявка" && r.manager_id === state.currentUser.id);

    return `
      <tr>
        <td data-label="№ Заявки"><b>#${r.id}</b></td>
        <td data-label="Должность"><b>${escapeHtml(r.title)}</b></td>
        <td data-label="Подразделение">${escapeHtml(r.department_name || "-")}</td>
        <td data-label="Дата открытия">${r.open_date}</td>
        <td data-label="План закрытия">${r.plan_close_date}</td>
        <td data-label="План найма">${r.hired_count} / ${r.count} чел.</td>
        <td data-label="Прогресс">
          <div class="progress-container">
            <div class="progress-bar-bg">
              <div class="progress-bar-fill" style="width: ${r.progress_pct}%"></div>
            </div>
            <span class="progress-text">${r.progress_pct}%</span>
          </div>
        </td>
        <td data-label="Рекрутер">${escapeHtml(r.recruiter_name || "Не назначен")}</td>
        <td data-label="Статус"><span class="badge ${badgeClass}">${escapeHtml(r.status)}</span></td>
        <td data-label="Действия">
          ${canEdit ? `<button class="btn btn-sm" onclick="editRequisition('${r.id}')">✏️ Редактировать</button>` : `<span style="font-size:0.8rem; color:var(--text-dim);">Только просмотр</span>`}
        </td>
      </tr>
    `;
  }).join("");
}

function openCreateRequisitionModal() {
  document.getElementById("modalReqTitle").textContent = "Создать новую заявку";
  document.getElementById("reqEditId").value = "";
  document.getElementById("reqTitleInput").value = "";
  document.getElementById("reqCountInput").value = "1";
  document.getElementById("reqSalaryInput").value = "";
  document.getElementById("reqReqsInput").value = "";
  
  const today = new Date().toISOString().split("T")[0];
  const nextMonth = new Date(Date.now() + 30 * 86400000).toISOString().split("T")[0];
  document.getElementById("reqOpenDate").value = today;
  document.getElementById("reqPlanDate").value = nextMonth;

  document.getElementById("reqRecruiterGroup").style.display = "none";
  document.getElementById("reqStatusGroup").style.display = "none";

  openModal("modalRequisition");
}

function editRequisition(id) {
  const req = state.requisitions.find(r => r.id === id);
  if (!req) return;

  document.getElementById("modalReqTitle").textContent = `Редактировать заявку №${req.id}`;
  document.getElementById("reqEditId").value = req.id;
  document.getElementById("reqTitleInput").value = req.title;
  document.getElementById("reqDeptInput").value = req.department_id || "";
  document.getElementById("reqCountInput").value = req.count;
  document.getElementById("reqOpenDate").value = req.open_date;
  document.getElementById("reqPlanDate").value = req.plan_close_date;
  document.getElementById("reqSalaryInput").value = req.salary || "";
  document.getElementById("reqReqsInput").value = req.requirements || "";

  const isDirectorOrAdmin = state.currentUser.roles.some(r => ["admin", "director"].includes(r));
  if (isDirectorOrAdmin) {
    document.getElementById("reqRecruiterGroup").style.display = "block";
    document.getElementById("reqStatusGroup").style.display = "block";
    document.getElementById("reqRecruiterInput").value = req.recruiter_id || "";
    document.getElementById("reqStatusInput").value = req.status;
  } else {
    document.getElementById("reqRecruiterGroup").style.display = "none";
    document.getElementById("reqStatusGroup").style.display = "none";
  }

  openModal("modalRequisition");
}

async function saveRequisition() {
  const editId = document.getElementById("reqEditId").value;
  const title = document.getElementById("reqTitleInput").value.trim();
  const deptId = parseInt(document.getElementById("reqDeptInput").value);
  const count = parseInt(document.getElementById("reqCountInput").value);
  const openDate = document.getElementById("reqOpenDate").value;
  const planDate = document.getElementById("reqPlanDate").value;
  const salary = document.getElementById("reqSalaryInput").value.trim();
  const reqs = document.getElementById("reqReqsInput").value.trim();

  if (!title || !deptId || !count || !openDate || !planDate) {
    showToast("Пожалуйста, заполните обязательные поля (*)", "error");
    return;
  }

  try {
    if (editId) {
      // Update
      const payload = {
        title: title,
        department_id: deptId,
        count: count,
        plan_close_date: planDate,
        salary: salary,
        requirements: reqs
      };

      const isDirectorOrAdmin = state.currentUser.roles.some(r => ["admin", "director"].includes(r));
      if (isDirectorOrAdmin) {
        const recVal = document.getElementById("reqRecruiterInput").value;
        payload.recruiter_id = recVal ? parseInt(recVal) : null;
        payload.status = document.getElementById("reqStatusInput").value;
      }

      await apiRequest(`/api/requisitions/${editId}`, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      showToast("Заявка успешно обновлена", "success");
    } else {
      // Create
      await apiRequest("/api/requisitions", {
        method: "POST",
        body: JSON.stringify({
          open_date: openDate,
          plan_close_date: planDate,
          department_id: deptId,
          title: title,
          count: count,
          salary: salary,
          requirements: reqs
        })
      });
      showToast("Новая заявка успешно создана", "success");
    }
    closeModal("modalRequisition");
    loadRequisitions();
  } catch (err) {
    console.error(err);
  }
}

// ==========================================================================
// TAB 2: Candidates & Talent Pool
// ==========================================================================
function debounceLoadCandidates() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    loadCandidates();
  }, 300);
}

async function loadCandidates() {
  const search = document.getElementById("candSearch").value.trim();
  const deptId = document.getElementById("candFilterDept").value;
  const status = document.getElementById("candFilterStatus").value;
  const reqId = document.getElementById("candFilterReq").value;

  let url = `/api/candidates?1=1`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (deptId) url += `&department_id=${deptId}`;
  if (status) url += `&hired_status=${encodeURIComponent(status)}`;
  if (reqId) url += `&requisition_id=${reqId}`;

  try {
    const data = await apiRequest(url);
    state.candidates = data;
    renderCandidatesTable(data);
  } catch (err) {
    console.error(err);
  }
}

function renderCandidatesTable(cands) {
  const tbody = document.getElementById("candidatesTableBody");
  if (!cands || cands.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--text-muted); padding:2rem;">Соискатели не найдены</td></tr>`;
    return;
  }

  tbody.innerHTML = cands.map(c => {
    let hiredBadge = "badge-process";
    if (c.hired_status === "Трудоустроен") hiredBadge = "badge-hired";
    if (c.hired_status === "Отказ") hiredBadge = "badge-rejected";

    let testBadge = `<span style="color:var(--text-dim);">Не проходил</span>`;
    if (c.test_result === "Сдал") testBadge = `<span style="color:var(--accent-emerald); font-weight:600;">✓ Сдал (${c.test_score || 0} б)</span>`;
    if (c.test_result === "Не сдал") testBadge = `<span style="color:var(--accent-rose); font-weight:600;">✗ Не сдал (${c.test_score || 0} б)</span>`;

    const resumeBtn = c.resume_path ?
      `<a href="${c.resume_path}" target="_blank" class="btn btn-sm btn-primary">📄 Открыть</a>` :
      `<span style="font-size:0.8rem; color:var(--text-dim);">Нет резюме</span>`;

    return `
      <tr>
        <td data-label="ID">#${c.id}</td>
        <td data-label="ФИО Кандидата">
          <a href="#" style="font-weight:700; text-decoration:none;" onclick="viewCandidateDetails(${c.id}); return false;">
            ${escapeHtml(c.cand_name)}
          </a>
        </td>
        <td data-label="Телефон">
          <a href="tel:${escapeHtml(c.phone)}" class="btn-phone-call">📞 ${escapeHtml(c.phone)}</a>
        </td>
        <td data-label="Должность / Заявка">
          <div style="font-weight:600;">${escapeHtml(c.title || "Должность не указана")}</div>
          <div style="font-size:0.78rem; color:var(--text-muted);">
            ${c.requisition_id ? `Заявка #${c.requisition_id}` : `<span style="color:var(--accent-amber);">Резерв</span>`}
          </div>
        </td>
        <td data-label="Тестирование">${testBadge}</td>
        <td data-label="Собеседование">
          <div style="font-size:0.85rem;">${c.interview_result ? escapeHtml(c.interview_result) : '-'}</div>
          ${c.offer_date ? `<div style="font-size:0.75rem; color:var(--accent-emerald);">Оффер: ${c.offer_date}</div>` : ''}
        </td>
        <td data-label="Статус"><span class="badge ${hiredBadge}">${escapeHtml(c.hired_status)}</span></td>
        <td data-label="Резюме">${resumeBtn}</td>
        <td data-label="Действия">
          <div style="display:flex; gap:6px;">
            <button class="btn btn-sm" onclick="viewCandidateDetails(${c.id})">👁️ Карточка</button>
            <button class="btn btn-sm" onclick="openBindCandidateModal(${c.id})">🔗 Привязать</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function updateCandidateReqSelect(reqs) {
  const select = document.getElementById("candFilterReq");
  const modalSelect = document.getElementById("candReqInput");
  const bindSelect = document.getElementById("bindReqSelect");

  let opts = '<option value="">Все заявки</option><option value="NONE">Без привязки (Резерв)</option>';
  let modalOpts = '<option value="">Без привязки (В общий резерв)</option>';

  reqs.forEach(r => {
    const label = `№${r.id} - ${r.title} (${r.department_name})`;
    opts += `<option value="${r.id}">${label}</option>`;
    modalOpts += `<option value="${r.id}">${label}</option>`;
  });

  if (select) select.innerHTML = opts;
  if (modalSelect) modalSelect.innerHTML = modalOpts;
  if (bindSelect) bindSelect.innerHTML = modalOpts;
}

function onCandidateReqSelectChange() {
  const reqId = document.getElementById("candReqInput").value;
  if (reqId) {
    const req = state.requisitions.find(r => r.id === reqId);
    if (req) {
      document.getElementById("candDeptInput").value = req.department_id || "";
      document.getElementById("candJobTitleInput").value = req.title || "";
    }
  }
}

function openCreateCandidateModal() {
  document.getElementById("modalCandTitle").textContent = "Добавить нового соискателя";
  document.getElementById("candEditId").value = "";
  document.getElementById("candNameInput").value = "";
  document.getElementById("candPhoneInput").value = "";
  document.getElementById("candReqInput").value = "";
  document.getElementById("candDeptInput").value = "";
  document.getElementById("candJobTitleInput").value = "";
  document.getElementById("candRecruiterInput").value = state.currentUser.id;
  document.getElementById("candComments").value = "";
  document.getElementById("candSalaryExp").value = "";

  document.getElementById("candExtendedFields").style.display = "none";
  openModal("modalCandidate");
}

function viewCandidateDetails(candId) {
  const cand = state.candidates.find(c => c.id === candId);
  if (!cand) return;

  document.getElementById("viewCandName").textContent = `Карточка Соискателя: ${cand.cand_name}`;
  
  const canDelete = state.currentUser.roles.some(r => ["admin", "director"].includes(r));
  const deleteBtn = document.getElementById("btnDeleteCand");
  if (deleteBtn) {
    deleteBtn.style.display = canDelete ? "inline-flex" : "none";
    deleteBtn.dataset.candId = cand.id;
  }

  const content = document.getElementById("viewCandContent");
  content.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; background:rgba(255,255,255,0.03); padding:1rem; border-radius:var(--radius-md);">
      <div>
        <h3 style="color:#fff; font-size:1.2rem;">${escapeHtml(cand.cand_name)}</h3>
        <p style="color:var(--text-muted); font-size:0.9rem;">📞 ${escapeHtml(cand.phone)} | 🏢 ${escapeHtml(cand.department_name || 'Резерв')}</p>
      </div>
      <div>
        <button class="btn btn-primary btn-sm" onclick="closeModal('modalViewCandidate'); editCandidate(${cand.id});">✏️ Редактировать карточку</button>
      </div>
    </div>

    <div class="form-grid" style="font-size:0.9rem; margin-bottom:1.5rem;">
      <div><b>Закрепленная заявка:</b> ${cand.requisition_id ? `№${cand.requisition_id} (${escapeHtml(cand.requisition_title || '')})` : 'Без привязки (Резерв)'}</div>
      <div><b>Рекрутер:</b> ${escapeHtml(cand.recruiter_name || 'Не назначен')}</div>
      <div><b>Дата создания:</b> ${cand.created_date || '-'}</div>
      <div><b>Статус найма:</b> <span class="badge ${cand.hired_status === 'Трудоустроен' ? 'badge-hired' : (cand.hired_status === 'Отказ' ? 'badge-rejected' : 'badge-process')}">${cand.hired_status}</span></div>
      <div><b>Недозвон:</b> ${cand.no_answer}</div>
      <div><b>Самоотказ:</b> ${cand.self_withdraw}</div>
      <div><b>Ожидаемая ЗП:</b> ${escapeHtml(cand.salary_expectation || 'Не указана')}</div>
      <div><b>Дата найма:</b> ${cand.hire_date || '-'}</div>
    </div>

    <div style="background:rgba(255,255,255,0.02); padding:1rem; border-radius:var(--radius-md); margin-bottom:1.5rem;">
      <h4 style="color:var(--accent-purple); margin-bottom:8px;">🧪 Результаты тестирования и интервью</h4>
      <div class="form-grid" style="font-size:0.88rem;">
        <div><b>Результат теста:</b> ${cand.test_result} (Балл: ${cand.test_score !== null ? cand.test_score : '-'})</div>
        <div><b>Дата/Время теста:</b> ${cand.test_date || '-'} ${cand.test_time || ''}</div>
        <div><b>Дата интервью:</b> ${cand.interview_date || '-'}</div>
        <div><b>Результат интервью:</b> ${escapeHtml(cand.interview_result || '-')}</div>
        <div><b>Дата оффера:</b> ${cand.offer_date || '-'}</div>
        <div><b>Результат оффера:</b> ${escapeHtml(cand.offer_result || '-')}</div>
      </div>
    </div>

    ${cand.general_reject_reason || cand.rec_reject_reason ? `
      <div style="background:rgba(244,63,94,0.1); border:1px solid rgba(244,63,94,0.3); padding:1rem; border-radius:var(--radius-md); margin-bottom:1.5rem; color:#fda4af;">
        <b>Причины отказа:</b> ${escapeHtml(cand.general_reject_reason || cand.rec_reject_reason)}
      </div>
    ` : ''}

    <div style="margin-bottom:1.5rem;">
      <b>Комментарии:</b>
      <p style="color:var(--text-muted); background:var(--bg-input); padding:10px; border-radius:var(--radius-sm); margin-top:4px;">
        ${escapeHtml(cand.comments || 'Комментариев нет')}
      </p>
    </div>

    <div style="border-top:1px solid var(--border-color); padding-top:1rem;">
      <h4 style="margin-bottom:10px; color:#fff;">📄 Прикрепленное резюме:</h4>
      ${cand.resume_path ? `
        <div style="display:flex; gap:10px; align-items:center;">
          <a href="${cand.resume_path}" target="_blank" class="btn btn-primary">📥 Открыть резюме в браузере</a>
          <button class="btn btn-danger btn-sm" onclick="deleteResume(${cand.id})">🗑️ Удалить файл</button>
        </div>
      ` : `
        <div style="display:flex; gap:10px; align-items:center;">
          <input type="file" id="resumeFileInput" accept=".pdf,.doc,.docx" class="form-control" style="flex:1;">
          <button class="btn btn-success" onclick="uploadResumeForCand(${cand.id})">Загрузить PDF/DOCX</button>
        </div>
      `}
    </div>
  `;

  openModal("modalViewCandidate");
}

function editCandidate(candId) {
  const cand = state.candidates.find(c => c.id === candId);
  if (!cand) return;

  document.getElementById("modalCandTitle").textContent = `Редактировать соискателя #${cand.id}`;
  document.getElementById("candEditId").value = cand.id;
  document.getElementById("candNameInput").value = cand.cand_name;
  document.getElementById("candPhoneInput").value = cand.phone;
  document.getElementById("candReqInput").value = cand.requisition_id || "";
  document.getElementById("candDeptInput").value = cand.department_id || "";
  document.getElementById("candJobTitleInput").value = cand.title || "";
  document.getElementById("candRecruiterInput").value = cand.recruiter_id || "";
  document.getElementById("candComments").value = cand.comments || "";
  document.getElementById("candSalaryExp").value = cand.salary_expectation || "";

  document.getElementById("candNoAnswer").value = cand.no_answer || "Нет";
  document.getElementById("candRecReject").value = cand.rec_reject_reason || "";
  document.getElementById("candSelfWithdraw").value = cand.self_withdraw || "Нет";
  document.getElementById("candTestDate").value = cand.test_date || "";
  document.getElementById("candTestTime").value = cand.test_time || "";
  document.getElementById("candTestScore").value = cand.test_score !== null ? cand.test_score : "";
  document.getElementById("candTestResult").value = cand.test_result || "Не проходил";
  document.getElementById("candInterviewDate").value = cand.interview_date || "";
  document.getElementById("candInterviewResult").value = cand.interview_result || "";
  document.getElementById("candOfferDate").value = cand.offer_date || "";
  document.getElementById("candOfferResult").value = cand.offer_result || "";
  document.getElementById("candGeneralReject").value = cand.general_reject_reason || "";
  document.getElementById("candHireDate").value = cand.hire_date || "";
  document.getElementById("candHiredStatus").value = cand.hired_status || "В процессе";

  document.getElementById("candExtendedFields").style.display = "block";
  openModal("modalCandidate");
}

async function saveCandidate() {
  const candId = document.getElementById("candEditId").value;
  const candName = document.getElementById("candNameInput").value.trim();
  const phone = document.getElementById("candPhoneInput").value.trim();
  const reqId = document.getElementById("candReqInput").value || null;
  const deptId = document.getElementById("candDeptInput").value ? parseInt(document.getElementById("candDeptInput").value) : null;
  const recruiterId = document.getElementById("candRecruiterInput").value ? parseInt(document.getElementById("candRecruiterInput").value) : state.currentUser.id;
  const title = document.getElementById("candJobTitleInput").value.trim();
  const comments = document.getElementById("candComments").value.trim();
  const salaryExp = document.getElementById("candSalaryExp").value.trim();

  if (!candName || !phone) {
    showToast("Укажите ФИО и телефон соискателя", "error");
    return;
  }

  try {
    if (candId) {
      // Update candidate with all 22 fields
      const payload = {
        requisition_id: reqId,
        recruiter_id: recruiterId,
        department_id: deptId,
        title: title,
        cand_name: candName,
        phone: phone,
        salary_expectation: salaryExp,
        comments: comments,
        no_answer: document.getElementById("candNoAnswer").value,
        rec_reject_reason: document.getElementById("candRecReject").value.trim(),
        self_withdraw: document.getElementById("candSelfWithdraw").value,
        test_date: document.getElementById("candTestDate").value || null,
        test_time: document.getElementById("candTestTime").value || null,
        test_score: document.getElementById("candTestScore").value ? parseInt(document.getElementById("candTestScore").value) : null,
        test_result: document.getElementById("candTestResult").value,
        interview_date: document.getElementById("candInterviewDate").value || null,
        interview_result: document.getElementById("candInterviewResult").value.trim(),
        offer_date: document.getElementById("candOfferDate").value || null,
        offer_result: document.getElementById("candOfferResult").value.trim(),
        general_reject_reason: document.getElementById("candGeneralReject").value.trim(),
        hire_date: document.getElementById("candHireDate").value || null,
        hired_status: document.getElementById("candHiredStatus").value
      };

      await apiRequest(`/api/candidates/${candId}`, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      showToast("Карточка соискателя успешно обновлена", "success");
    } else {
      // Create new candidate
      await apiRequest("/api/candidates", {
        method: "POST",
        body: JSON.stringify({
          requisition_id: reqId,
          recruiter_id: recruiterId,
          department_id: deptId,
          title: title,
          cand_name: candName,
          phone: phone,
          salary_expectation: salaryExp,
          comments: comments
        })
      });
      showToast("Соискатель успешно добавлен в базу", "success");
    }
    closeModal("modalCandidate");
    loadCandidates();
  } catch (err) {
    console.error(err);
  }
}

function openBindCandidateModal(candId) {
  const cand = state.candidates.find(c => c.id === candId);
  if (!cand) return;

  document.getElementById("bindCandId").value = cand.id;
  document.getElementById("bindCandNameDisplay").textContent = cand.cand_name;
  document.getElementById("bindReqSelect").value = cand.requisition_id || "";

  openModal("modalBindCandidate");
}

async function executeCandidateBind() {
  const candId = document.getElementById("bindCandId").value;
  const reqId = document.getElementById("bindReqSelect").value || null;

  try {
    const res = await apiRequest(`/api/candidates/${candId}/bind`, {
      method: "POST",
      body: JSON.stringify({ requisition_id: reqId })
    });
    showToast(res.message, "success");
    closeModal("modalBindCandidate");
    loadCandidates();
  } catch (err) {
    console.error(err);
  }
}

async function uploadResumeForCand(candId) {
  const fileInput = document.getElementById("resumeFileInput");
  if (!fileInput || !fileInput.files[0]) {
    showToast("Выберите файл резюме (PDF/DOCX)", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  try {
    const res = await apiRequest(`/api/candidates/upload-resume?cand_id=${candId}`, {
      method: "POST",
      body: formData
    });
    showToast(res.message, "success");
    viewCandidateDetails(candId);
    loadCandidates();
  } catch (err) {
    console.error(err);
  }
}

async function deleteResume(candId) {
  if (!confirm("Вы действительно хотите удалить прикрепленное резюме?")) return;
  try {
    await apiRequest(`/api/candidates/${candId}/resume`, { method: "DELETE" });
    showToast("Резюме удалено", "info");
    viewCandidateDetails(candId);
    loadCandidates();
  } catch (err) {
    console.error(err);
  }
}

async function deleteCandidateFromModal() {
  const candId = document.getElementById("btnDeleteCand").dataset.candId;
  if (!candId) return;
  if (!confirm("Вы уверены, что хотите полностью удалить запись соискателя из базы?")) return;

  try {
    await apiRequest(`/api/candidates/${candId}`, { method: "DELETE" });
    showToast("Соискатель удален", "success");
    closeModal("modalViewCandidate");
    loadCandidates();
  } catch (err) {
    console.error(err);
  }
}

function exportCandidatesCSV() {
  window.open(`${API_BASE}/api/candidates/export`, "_blank");
}

// ==========================================================================
// TAB 3: Executive Analytics
// ==========================================================================
async function loadExecutiveAnalytics() {
  try {
    const data = await apiRequest("/api/analytics/executive");
    
    // KPIs
    document.getElementById("kpiFulfillment").textContent = `${data.kpi.fulfillment_percentage}%`;
    document.getElementById("kpiSlaDays").textContent = `${data.kpi.average_sla_days} дн.`;
    document.getElementById("kpiActiveFunnel").textContent = data.kpi.active_funnel_count;
    document.getElementById("kpiOnTime").textContent = `${data.kpi.on_time_percentage}%`;

    // Department progress list
    const deptContainer = document.getElementById("deptProgressList");
    deptContainer.innerHTML = data.department_progress.map(d => `
      <div class="dept-item">
        <div class="dept-info">
          <span>${escapeHtml(d.department_name)}</span>
          <span style="color:var(--text-muted);">${d.hired} из ${d.plan} чел. (${d.percentage}%)</span>
        </div>
        <div class="progress-bar-bg" style="height:10px;">
          <div class="progress-bar-fill" style="width: ${d.percentage}%;"></div>
        </div>
      </div>
    `).join("");

    // SLA Indicators table
    const slaTbody = document.getElementById("slaTableBody");
    slaTbody.innerHTML = data.sla_indicators.map(s => {
      let statusBadge = `<span class="badge badge-closed">В норме</span>`;
      if (s.is_overdue) {
        statusBadge = `<span class="badge badge-rejected">🚨 Просрочена (${Math.abs(s.days_left)} дн)</span>`;
      } else if (s.days_left <= 5) {
        statusBadge = `<span class="badge badge-working">⚠️ Требует внимания (${s.days_left} дн)</span>`;
      }

      return `
        <tr>
          <td><b>#${s.requisition_id}</b></td>
          <td><b>${escapeHtml(s.title)}</b></td>
          <td>${escapeHtml(s.department)}</td>
          <td>${s.open_date}</td>
          <td>${s.plan_close_date}</td>
          <td>${escapeHtml(s.recruiter_name)}</td>
          <td><b>${s.days_left} дн.</b></td>
          <td>${statusBadge}</td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    console.error(err);
  }
}

// ==========================================================================
// TAB 4: Recruiter Analytics
// ==========================================================================
async function loadRecruiterAnalytics() {
  try {
    const data = await apiRequest("/api/analytics/recruiters");
    const tbody = document.getElementById("recruitersTableBody");
    if (!data || data.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color:var(--text-muted);">Данные аналитики не найдены</td></tr>`;
      return;
    }

    tbody.innerHTML = data.map(r => `
      <tr>
        <td><b>${escapeHtml(r.name)}</b></td>
        <td>${r.total_candidates}</td>
        <td><b style="color:var(--accent-emerald);">${r.hired_count}</b></td>
        <td><span style="color:${r.no_answer_count > 0 ? 'var(--accent-rose)' : 'inherit'};">${r.no_answer_count}</span></td>
        <td>
          <div class="progress-container">
            <div class="progress-bar-bg">
              <div class="progress-bar-fill" style="width: ${r.conversion_pct}%;"></div>
            </div>
            <span class="progress-text">${r.conversion_pct}%</span>
          </div>
        </td>
        <td><b>${r.avg_test_score}</b> / 100</td>
      </tr>
    `).join("");

  } catch (err) {
    console.error(err);
  }
}

// ==========================================================================
// TAB 5: Admin Users
// ==========================================================================
async function loadAdminUsers() {
  try {
    const users = await apiRequest("/api/admin/users");
    const tbody = document.getElementById("usersTableBody");

    tbody.innerHTML = users.map(u => `
      <tr>
        <td>#${u.id}</td>
        <td><b>${escapeHtml(u.first_name)} ${escapeHtml(u.last_name)}</b></td>
        <td>${escapeHtml(u.username_email)}</td>
        <td>${escapeHtml(u.phone)}</td>
        <td>${escapeHtml(u.factory_name || '-')}</td>
        <td>${escapeHtml(u.department_name || '-')}</td>
        <td>
          ${u.role_names.map(rn => `<span class="user-role-badge" style="margin-right:4px;">${escapeHtml(rn)}</span>`).join("")}
        </td>
        <td>
          <span class="badge ${u.status === 'active' ? 'badge-closed' : 'badge-rejected'}">
            ${u.status === 'active' ? 'Активен' : 'Заблокирован'}
          </span>
        </td>
        <td>
          <button class="btn btn-sm" onclick="editUser(${u.id})">✏️ Редактировать</button>
        </td>
      </tr>
    `).join("");

    state.adminUsers = users;
  } catch (err) {
    console.error(err);
  }
}

function openCreateUserModal() {
  document.getElementById("modalUserTitle").textContent = "Добавить пользователя (Супер Админ)";
  document.getElementById("userEditId").value = "";
  document.getElementById("userFirstName").value = "";
  document.getElementById("userLastName").value = "";
  document.getElementById("userEmail").value = "";
  document.getElementById("userPhone").value = "";
  document.getElementById("userPosition").value = "";
  document.getElementById("userPin").value = "1234";

  document.querySelectorAll("input[name='userRoleCode']").forEach(cb => cb.checked = false);
  document.querySelectorAll("input[name='userPermCode']").forEach(cb => {
    cb.checked = ["can_view_all_requisitions", "can_manage_candidates"].includes(cb.value);
  });

  openModal("modalUser");
}

function editUser(userId) {
  const u = state.adminUsers ? state.adminUsers.find(x => x.id === userId) : null;
  if (!u) return;

  document.getElementById("modalUserTitle").textContent = `Редактировать пользователя #${u.id}`;
  document.getElementById("userEditId").value = u.id;
  document.getElementById("userFirstName").value = u.first_name;
  document.getElementById("userLastName").value = u.last_name;
  document.getElementById("userEmail").value = u.username_email;
  document.getElementById("userPhone").value = u.phone;
  document.getElementById("userPosition").value = u.position || "";
  document.getElementById("userPin").value = "";
  if (document.getElementById("userFactory")) document.getElementById("userFactory").value = u.factory_id || 1;
  if (document.getElementById("userDept")) document.getElementById("userDept").value = u.department_id || 1;

  document.querySelectorAll("input[name='userRoleCode']").forEach(cb => {
    cb.checked = u.roles.includes(cb.value);
  });

  let uPerms = [];
  try {
    uPerms = typeof u.permissions === "string" ? JSON.parse(u.permissions || "[]") : (u.permissions || []);
  } catch (e) { uPerms = []; }

  document.querySelectorAll("input[name='userPermCode']").forEach(cb => {
    cb.checked = uPerms.includes(cb.value);
  });

  openModal("modalUser");
}

async function saveUser() {
  const userId = document.getElementById("userEditId").value;
  const firstName = document.getElementById("userFirstName").value.trim();
  const lastName = document.getElementById("userLastName").value.trim();
  const email = document.getElementById("userEmail").value.trim();
  const phone = document.getElementById("userPhone").value.trim();
  const position = document.getElementById("userPosition").value.trim();
  const pin = document.getElementById("userPin").value.trim();
  const factoryId = parseInt(document.getElementById("userFactory").value || "1");
  const deptId = parseInt(document.getElementById("userDept").value || "1");

  const roles = Array.from(document.querySelectorAll("input[name='userRoleCode']:checked")).map(cb => cb.value);
  const permissions = Array.from(document.querySelectorAll("input[name='userPermCode']:checked")).map(cb => cb.value);

  if (!firstName || !lastName || !email || !phone || !position || roles.length === 0) {
    showToast("Заполните имя, фамилию, email, телефон, должность и выберите хотя бы одну роль", "error");
    return;
  }

  try {
    if (userId) {
      // Update
      const payload = {
        first_name: firstName,
        last_name: lastName,
        phone: phone,
        factory_id: factoryId,
        department_id: deptId,
        position: position,
        permissions: permissions,
        roles: roles
      };
      if (pin) payload.pin = pin;

      await apiRequest(`/api/admin/users/${userId}`, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      showToast("Данные пользователя обновлены", "success");
    } else {
      // Create
      if (!pin) {
        showToast("Укажите PIN-код / пароль для нового пользователя", "error");
        return;
      }
      await apiRequest("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({
          username_email: email,
          first_name: firstName,
          last_name: lastName,
          phone: phone,
          pin: pin,
          factory_id: factoryId,
          department_id: deptId,
          position: position,
          permissions: permissions,
          roles: roles
        })
      });
      showToast("Пользователь успешно создан Супер Админом", "success");
    }
    closeModal("modalUser");
    loadAdminUsers();
  } catch (err) {
    console.error(err);
  }
}

// ==========================================================================
// Helpers & Utilities
// ==========================================================================
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add("active");
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove("active");
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${escapeHtml(message)}</span>`;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}
