// Interfaz de pvlt. Sin dependencias externas.
//
// Reglas de esta página:
// - Los datos de la bóveda se escriben solo con textContent, nunca con innerHTML.
// - El token de arranque llega en el fragmento, se canjea una vez y se borra de la URL.
// - Ningún dato del usuario viaja en la URL. La búsqueda se hace aquí sobre la lista.
// - El portapapeles se vacía a los 20 s con writeText(""), sin leerlo antes.
"use strict";

(() => {
  const CLIPBOARD_SECONDS = 20;
  const POLL_MS = 10000;
  const CSRF_KEY = "pvlt.csrf";

  const CONFLICTS = { id: "mismo identificador", site_username: "mismo sitio y usuario" };
  const PANELS = [
    "panel-detail", "panel-entry", "panel-generator", "panel-change",
    "panel-export", "panel-import", "panel-settings",
  ];
  const VIEWS = ["view-boot", "view-no-session", "view-create", "view-unlock", "view-main"];

  const state = {
    csrf: null,
    entries: [],
    current: null,      // id de la entrada abierta en el panel
    editing: null,      // id de la entrada en edición, o null si es nueva
    preview: null,      // vista previa de importación
    clipTimer: null,
    noticeTimer: null,
  };

  const $ = (id) => document.getElementById(id);

  // --- Comunicación con el servidor ---------------------------------------------

  class ApiError extends Error {
    constructor(status, data) {
      super((data && data.message) || `Error ${status}`);
      this.status = status;
      this.code = data && data.error;
      this.field = data && data.field;
    }
  }

  async function api(method, path, body) {
    const headers = {};
    if (state.csrf) headers["X-CSRF-Token"] = state.csrf;
    const init = { method, headers, credentials: "same-origin", cache: "no-store" };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const response = await fetch(path, init);
    let data = null;
    try {
      data = await response.json();
    } catch (_) {
      data = null;
    }
    if (!response.ok) throw new ApiError(response.status, data);
    return data;
  }

  function storeCsrf(value) {
    state.csrf = value;
    try {
      sessionStorage.setItem(CSRF_KEY, value);
    } catch (_) {
      // Sin almacenamiento la sesión sigue funcionando hasta recargar.
    }
  }

  function loadCsrf() {
    try {
      return sessionStorage.getItem(CSRF_KEY);
    } catch (_) {
      return null;
    }
  }

  // --- Mensajes -----------------------------------------------------------------

  function notice(text) {
    const el = $("notice");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(state.noticeTimer);
    state.noticeTimer = setTimeout(() => { el.hidden = true; }, 8000);
  }

  function showError(text) {
    const el = $("error");
    el.textContent = text;
    el.hidden = !text;
  }

  function fail(error) {
    if (error instanceof ApiError && error.status === 423) {
      toLocked("La bóveda se bloqueó. Vuelve a desbloquearla.");
      return;
    }
    if (error instanceof ApiError && error.status === 401) {
      showNoSession(error.message);
      return;
    }
    showError(error instanceof ApiError ? error.message : "No se pudo contactar con pvlt.");
  }

  // Ejecuta una acción y traduce cualquier error a un mensaje.
  function guarded(action) {
    return async (event) => {
      if (event && event.preventDefault) event.preventDefault();
      showError("");
      try {
        await action(event);
      } catch (error) {
        fail(error);
      }
    };
  }

  // --- Vistas -------------------------------------------------------------------

  function showView(id) {
    for (const view of VIEWS) $(view).hidden = view !== id;
    $("lock-button").hidden = id !== "view-main";
  }

  function showPanel(id) {
    for (const panel of PANELS) $(panel).hidden = panel !== id;
    $("panel-empty").hidden = id !== null;
  }

  function showNoSession(reason) {
    clearSecrets();
    $("no-session-reason").textContent = reason || "";
    $("recovery").hidden = true;
    showView("view-no-session");
  }

  function clearSecrets() {
    state.entries = [];
    state.current = null;
    state.editing = null;
    state.preview = null;
    $("entries-body").replaceChildren();
    $("import-items").replaceChildren();
    $("import-preview").hidden = true;
    for (const id of [
      "create-password", "create-confirm", "unlock-password", "entry-site", "entry-username",
      "entry-password", "entry-notes", "change-current", "change-new", "change-confirm",
      "export-password", "export-confirm", "import-password", "search",
    ]) {
      $(id).value = "";
    }
    for (const id of [
      "detail-site", "detail-username", "detail-notes", "detail-created", "detail-modified",
      "gen-output", "gen-entropy", "entries-count",
    ]) {
      $(id).textContent = "";
    }
    hidePassword();
    $("gen-copy").hidden = true;
    showPanel(null);
  }

  function toLocked(message) {
    clearSecrets();
    showView("view-unlock");
    $("autolock").textContent = "";
    if (message) notice(message);
  }

  function renderRecovery(status) {
    const rollback = $("rollback-warning");
    rollback.hidden = !status.possible_rollback;
    rollback.textContent = status.possible_rollback
      ? `Aviso: el respaldo es más reciente que la bóveda (generación ${status.backup_generation} ` +
        `frente a ${status.vault_generation}). La bóveda podría ser una copia antigua.`
      : "";

    const damaged = $("damaged-warning");
    const states = {
      missing: "No hay bóveda en esta carpeta",
      unrecognized: "La bóveda tiene un formato no reconocido",
      corrupted: "La bóveda está dañada",
    };
    damaged.hidden = !status.can_restore_backup;
    damaged.textContent = status.can_restore_backup
      ? `${states[status.vault]}, pero el respaldo está bien (generación ${status.backup_generation}). ` +
        "Al restaurarlo el archivo actual se conserva aparte."
      : "";
    $("restore-button").hidden = !status.can_restore_backup;

    const temporaries = $("temporaries-warning");
    temporaries.hidden = status.removed_temporaries === 0;
    temporaries.textContent = status.removed_temporaries
      ? `Aviso: se eliminaron ${status.removed_temporaries} temporales de un guardado interrumpido.`
      : "";

    $("recovery").hidden = rollback.hidden && damaged.hidden && temporaries.hidden;
  }

  function renderAutolock(status) {
    const seconds = Math.round(status.seconds_until_autolock || 0);
    $("autolock").textContent = status.unlocked ? `Bloqueo automático en ${seconds} s` : "";
  }

  async function refresh() {
    const status = await api("GET", "/api/status");
    $("vault-name").textContent = status.vault_name;
    renderRecovery(status);
    renderAutolock(status);
    if (status.unlocked) {
      showView("view-main");
      await loadEntries();
      return;
    }
    clearSecrets();
    if (status.vault === "missing" && !status.can_restore_backup) {
      showView("view-create");
    } else if (status.vault === "unrecognized" || status.vault === "corrupted") {
      showView("view-unlock");
      if (!status.can_restore_backup) {
        showError(status.vault === "corrupted" ? "Archivo dañado" : "Formato no reconocido");
      }
    } else {
      showView(status.vault === "missing" ? "view-create" : "view-unlock");
    }
  }

  async function poll() {
    if (!state.csrf || $("view-main").hidden) return;
    try {
      const status = await api("GET", "/api/status");
      renderAutolock(status);
      if (!status.unlocked) toLocked("La bóveda se bloqueó por inactividad.");
    } catch (error) {
      fail(error);
    }
  }

  // --- Lista --------------------------------------------------------------------

  function cell(text) {
    const td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  function button(label, onClick, className) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    if (className) b.className = className;
    b.addEventListener("click", guarded(onClick));
    return b;
  }

  async function loadEntries() {
    const data = await api("GET", "/api/entries");
    state.entries = data.entries;
    renderEntries();
  }

  function renderEntries() {
    const query = $("search").value.trim().toLocaleLowerCase();
    const body = $("entries-body");
    body.replaceChildren();
    let shown = 0;
    for (const entry of state.entries) {
      const site = entry.site.toLocaleLowerCase();
      const user = entry.username.toLocaleLowerCase();
      if (query && !site.includes(query) && !user.includes(query)) continue;
      const row = document.createElement("tr");
      row.dataset.id = entry.id;
      const actions = document.createElement("td");
      actions.className = "row-actions";
      actions.append(
        button("Ver", () => openDetail(entry.id), "secondary"),
        button("Copiar", () => copyPassword(entry.id)),
      );
      row.append(cell(entry.site), cell(entry.username || "—"), cell(entry.modified), actions);
      body.append(row);
      shown += 1;
    }
    $("entries-empty").hidden = shown !== 0;
    $("entries-count").textContent =
      `${shown} de ${state.entries.length} entradas` + (query ? " (filtradas)" : "");
  }

  // --- Detalle ------------------------------------------------------------------

  function hidePassword() {
    const el = $("detail-password");
    el.textContent = "••••••••";
    el.dataset.shown = "";
    $("detail-show").textContent = "Ver";
  }

  async function openDetail(id) {
    const entry = await api("GET", `/api/entries/${encodeURIComponent(id)}`);
    state.current = entry.id;
    $("detail-site").textContent = entry.site;
    $("detail-username").textContent = entry.username || "—";
    $("detail-notes").textContent = entry.notes;
    $("detail-created").textContent = entry.created;
    $("detail-modified").textContent = entry.modified;
    hidePassword();
    showPanel("panel-detail");
  }

  async function togglePassword() {
    const el = $("detail-password");
    if (el.dataset.shown) {
      hidePassword();
      return;
    }
    const data = await api("GET", `/api/entries/${encodeURIComponent(state.current)}/password`);
    el.textContent = data.password;
    el.dataset.shown = "1";
    $("detail-show").textContent = "Ocultar";
  }

  async function writeClipboard(value) {
    await navigator.clipboard.writeText(value);
    clearTimeout(state.clipTimer);
    state.clipTimer = setTimeout(() => {
      state.clipTimer = null;
      // Se sobrescribe sin leer antes. No ocurre si la pestaña ya se cerró.
      navigator.clipboard.writeText("").then(
        () => notice("Portapapeles vaciado."),
        () => notice("No se pudo vaciar el portapapeles. Vacíalo a mano."),
      );
    }, CLIPBOARD_SECONDS * 1000);
    notice(
      `Contraseña copiada. El portapapeles se vaciará en ${CLIPBOARD_SECONDS} s ` +
      "(no ocurre si cierras la pestaña antes).",
    );
  }

  async function copyPassword(id) {
    const data = await api("GET", `/api/entries/${encodeURIComponent(id)}/password`);
    await writeClipboard(data.password);
  }

  async function deleteCurrent() {
    if (!state.current) return;
    if (!window.confirm("¿Eliminar esta entrada? No se puede deshacer.")) return;
    await api("DELETE", `/api/entries/${encodeURIComponent(state.current)}`);
    state.current = null;
    showPanel(null);
    await loadEntries();
    notice("Entrada eliminada.");
  }

  // --- Alta y edición -----------------------------------------------------------

  function setPasswordVisible(visible) {
    $("entry-password").type = visible ? "text" : "password";
    $("entry-toggle").textContent = visible ? "Ocultar" : "Mostrar";
  }

  function openNewEntry() {
    state.editing = null;
    $("entry-title").textContent = "Nueva entrada";
    for (const id of ["entry-site", "entry-username", "entry-password", "entry-notes"]) {
      $(id).value = "";
    }
    $("entry-password").required = true;
    $("entry-password-hint").hidden = true;
    setPasswordVisible(false);
    showPanel("panel-entry");
    $("entry-site").focus();
  }

  async function openEdit() {
    const entry = await api("GET", `/api/entries/${encodeURIComponent(state.current)}`);
    state.editing = entry.id;
    $("entry-title").textContent = "Editar entrada";
    $("entry-site").value = entry.site;
    $("entry-username").value = entry.username;
    $("entry-notes").value = entry.notes;
    $("entry-password").value = "";
    $("entry-password").required = false;
    $("entry-password-hint").hidden = false;
    setPasswordVisible(false);
    showPanel("panel-entry");
  }

  async function saveEntry() {
    const body = {
      site: $("entry-site").value,
      username: $("entry-username").value,
      notes: $("entry-notes").value,
    };
    const password = $("entry-password").value;
    let entry;
    if (state.editing) {
      if (password) body.password = password;
      entry = await api("PUT", `/api/entries/${encodeURIComponent(state.editing)}`, body);
    } else {
      body.password = password;
      entry = await api("POST", "/api/entries", body);
    }
    $("entry-password").value = "";
    state.editing = null;
    await loadEntries();
    await openDetail(entry.id);
    notice("Entrada guardada.");
  }

  // --- Generador ----------------------------------------------------------------

  function generatorSettings() {
    return {
      length: Number.parseInt($("gen-length").value, 10) || 0,
      lower: $("gen-lower").checked,
      upper: $("gen-upper").checked,
      digits: $("gen-digits").checked,
      symbols: $("gen-symbols").checked,
    };
  }

  function fillGenerator(settings) {
    $("gen-length").value = String(settings.length);
    $("gen-lower").checked = settings.lower;
    $("gen-upper").checked = settings.upper;
    $("gen-digits").checked = settings.digits;
    $("gen-symbols").checked = settings.symbols;
  }

  async function openGenerator() {
    const settings = await api("GET", "/api/settings");
    fillGenerator(settings.generator);
    showPanel("panel-generator");
  }

  async function runGenerator() {
    const data = await api("POST", "/api/generate", generatorSettings());
    $("gen-output").textContent = data.password;
    $("gen-entropy").textContent = `Entropía: ${data.entropy_bits.toFixed(1)} bits (cota superior)`;
    $("gen-copy").hidden = false;
  }

  async function saveGenerator() {
    await api("PUT", "/api/settings", { generator: generatorSettings() });
    notice("Generador guardado como predeterminado.");
  }

  async function generateIntoEntry() {
    const settings = await api("GET", "/api/settings");
    const data = await api("POST", "/api/generate", settings.generator);
    $("entry-password").value = data.password;
    setPasswordVisible(true);
    notice(`Contraseña generada: ${data.entropy_bits.toFixed(1)} bits (cota superior).`);
  }

  // --- Contraseña maestra, exportación, importación y ajustes -----------------------

  async function changePassword() {
    const body = {
      current: $("change-current").value,
      new: $("change-new").value,
      confirm: $("change-confirm").value,
    };
    try {
      await api("POST", "/api/change-password", body);
    } finally {
      for (const id of ["change-current", "change-new", "change-confirm"]) $(id).value = "";
    }
    showPanel(null);
    notice("Contraseña maestra cambiada. El respaldo también usa la nueva.");
  }

  async function exportVault() {
    const body = {
      filename: $("export-filename").value.trim(),
      password: $("export-password").value,
      confirm: $("export-confirm").value,
      overwrite: $("export-overwrite").checked,
    };
    let data;
    try {
      data = await api("POST", "/api/export", body);
    } finally {
      $("export-password").value = "";
      $("export-confirm").value = "";
    }
    notice(`Exportadas ${data.entries} entradas a ${data.filename}.`);
  }

  async function openImport() {
    const data = await api("GET", "/api/files");
    const select = $("import-file");
    select.replaceChildren();
    for (const name of data.files) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.append(option);
    }
    $("import-preview").hidden = true;
    state.preview = null;
    showPanel("panel-import");
    if (!data.files.length) showError("No hay archivos .pvlt para importar en la carpeta de la bóveda.");
  }

  async function previewImport() {
    const body = { filename: $("import-file").value, password: $("import-password").value };
    let data;
    try {
      data = await api("POST", "/api/import/preview", body);
    } finally {
      $("import-password").value = "";
    }
    state.preview = data;
    const rows = $("import-items");
    rows.replaceChildren();
    for (const item of data.items) {
      const row = document.createElement("tr");
      const decision = document.createElement("td");
      if (item.conflict) {
        const select = document.createElement("select");
        select.dataset.id = item.id;
        for (const [value, label] of [
          ["skip", "Omitir"], ["replace", "Sustituir"], ["keep_both", "Conservar ambas"],
        ]) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          select.append(option);
        }
        decision.append(select);
      } else {
        decision.textContent = "Añadir";
      }
      row.append(
        cell(item.site),
        cell(item.username || "—"),
        cell(item.conflict ? CONFLICTS[item.conflict] : "—"),
        decision,
      );
      rows.append(row);
    }
    $("import-summary").textContent =
      `El archivo tiene ${data.items.length} entradas, ${data.conflicts} en conflicto.`;
    $("import-preview").hidden = false;
  }

  async function applyImport() {
    if (!state.preview) return;
    const decisions = {};
    for (const select of $("import-items").querySelectorAll("select")) {
      decisions[select.dataset.id] = select.value;
    }
    const result = await api("POST", "/api/import/apply", {
      preview_id: state.preview.preview_id,
      decisions,
    });
    state.preview = null;
    $("import-items").replaceChildren();
    $("import-preview").hidden = true;
    showPanel(null);
    await loadEntries();
    notice(
      `Importación aplicada: ${result.added} añadidas, ${result.replaced} sustituidas, ` +
      `${result.kept_both} duplicadas con identificador nuevo, ${result.skipped} omitidas.`,
    );
  }

  async function openSettings() {
    const settings = await api("GET", "/api/settings");
    $("settings-autolock").value = String(settings.autolock_seconds);
    showPanel("panel-settings");
  }

  async function saveSettings() {
    const seconds = Number.parseInt($("settings-autolock").value, 10) || 0;
    await api("PUT", "/api/settings", { autolock_seconds: seconds });
    notice("Ajustes guardados.");
  }

  // --- Crear, desbloquear, bloquear y restaurar ----------------------------------

  async function createVault() {
    const body = {
      password: $("create-password").value,
      confirm: $("create-confirm").value,
      config: $("create-config").value,
    };
    try {
      await api("POST", "/api/create", body);
    } finally {
      $("create-password").value = "";
      $("create-confirm").value = "";
    }
    await refresh();
    notice("Bóveda creada.");
  }

  async function unlockVault() {
    const password = $("unlock-password").value;
    try {
      await api("POST", "/api/unlock", { password });
    } finally {
      $("unlock-password").value = "";
    }
    $("notice").hidden = true;
    await refresh();
  }

  async function lockVault() {
    await api("POST", "/api/lock");
    toLocked("Bóveda bloqueada.");
  }

  async function restoreBackup() {
    const question = "¿Restaurar el respaldo? El archivo actual se conserva aparte para su análisis.";
    if (!window.confirm(question)) return;
    const data = await api("POST", "/api/restore-backup", { confirm: true });
    await refresh();
    notice(data.kept ? `Respaldo restaurado. El archivo anterior se guardó como ${data.kept}.`
      : "Respaldo restaurado.");
  }

  // --- Arranque -----------------------------------------------------------------

  function bind() {
    $("create-form").addEventListener("submit", guarded(createVault));
    $("unlock-form").addEventListener("submit", guarded(unlockVault));
    $("lock-button").addEventListener("click", guarded(lockVault));
    $("restore-button").addEventListener("click", guarded(restoreBackup));

    $("search").addEventListener("input", renderEntries);
    $("new-entry-button").addEventListener("click", openNewEntry);
    $("generator-button").addEventListener("click", guarded(openGenerator));
    $("change-button").addEventListener("click", () => showPanel("panel-change"));
    $("export-button").addEventListener("click", () => showPanel("panel-export"));
    $("import-button").addEventListener("click", guarded(openImport));
    $("settings-button").addEventListener("click", guarded(openSettings));

    $("detail-show").addEventListener("click", guarded(togglePassword));
    $("detail-copy").addEventListener("click", guarded(() => copyPassword(state.current)));
    $("detail-edit").addEventListener("click", guarded(openEdit));
    $("detail-delete").addEventListener("click", guarded(deleteCurrent));

    $("entry-form").addEventListener("submit", guarded(saveEntry));
    $("entry-cancel").addEventListener("click", () => {
      $("entry-password").value = "";
      showPanel(state.current ? "panel-detail" : null);
    });
    $("entry-toggle").addEventListener("click", () => {
      setPasswordVisible($("entry-password").type === "password");
    });
    $("entry-generate").addEventListener("click", guarded(generateIntoEntry));

    $("generator-form").addEventListener("submit", guarded(runGenerator));
    $("gen-save").addEventListener("click", guarded(saveGenerator));
    $("gen-copy").addEventListener("click", guarded(() => writeClipboard($("gen-output").textContent)));

    $("change-form").addEventListener("submit", guarded(changePassword));
    $("export-form").addEventListener("submit", guarded(exportVault));
    $("import-form").addEventListener("submit", guarded(previewImport));
    $("import-apply").addEventListener("click", guarded(applyImport));
    $("import-cancel").addEventListener("click", () => {
      state.preview = null;
      $("import-items").replaceChildren();
      $("import-preview").hidden = true;
    });
    $("settings-form").addEventListener("submit", guarded(saveSettings));
  }

  async function boot() {
    bind();
    const match = /^#t=([A-Za-z0-9_-]+)$/.exec(window.location.hash);
    // El fragmento se borra antes de nada para que no quede en el historial.
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname);
    }
    if (match) {
      try {
        const data = await api("POST", "/api/session", { token: match[1] });
        storeCsrf(data.csrf);
      } catch (error) {
        showNoSession(error instanceof ApiError ? error.message : "");
        return;
      }
    } else {
      state.csrf = loadCsrf();
    }
    if (!state.csrf) {
      showNoSession("");
      return;
    }
    try {
      await refresh();
    } catch (error) {
      fail(error);
      return;
    }
    setInterval(poll, POLL_MS);
  }

  document.addEventListener("DOMContentLoaded", () => {
    boot();
  });
})();
