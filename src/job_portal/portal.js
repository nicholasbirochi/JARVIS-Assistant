(function () {
  var FILTER_KEY = "jarvis_portal_filtro_v1";
  var SELECT_KEY = "jarvis_portal_selecionadas_v1";
  var MIGRATION_KEY = "jarvis_portal_migrou_internacional_v1";

  function loadSet(key, fallback) {
    try {
      var saved = JSON.parse(localStorage.getItem(key) || "null");
      if (Array.isArray(saved)) return new Set(saved);
    } catch (e) {}
    return new Set(fallback);
  }
  function saveSet(key, set) {
    try { localStorage.setItem(key, JSON.stringify(Array.from(set))); } catch (e) {}
  }

  var activeTiers = loadSet(FILTER_KEY, ["internacional", "banco", "fintech", "bigtech", "startup", "outras"]);
  // 2026-09-05: a filter set saved before "internacional" existed could
  // never contain it -- it wasn't toggled off, it simply didn't exist
  // yet. Without this one-time migration, a returning visitor's stale
  // localStorage would silently hide the very section Nicholas just
  // asked to focus on. Runs once per browser (tracked by its own flag),
  // so a later, deliberate toggle-off is respected afterwards.
  try {
    if (!localStorage.getItem(MIGRATION_KEY)) {
      if (!activeTiers.has("internacional")) {
        activeTiers.add("internacional");
        saveSet(FILTER_KEY, activeTiers);
      }
      localStorage.setItem(MIGRATION_KEY, "1");
    }
  } catch (e) {}
  var selected = loadSet(SELECT_KEY, []);

  function applyTierFilter() {
    var anyVisible = false;
    document.querySelectorAll(".tier-section").forEach(function (s) {
      var visible = activeTiers.has(s.getAttribute("data-tier"));
      s.classList.toggle("tier-hidden", !visible);
      if (visible) anyVisible = true;
    });
    document.querySelectorAll(".filter-chip").forEach(function (c) {
      c.setAttribute("aria-pressed", activeTiers.has(c.getAttribute("data-tier")) ? "true" : "false");
    });
    var note = document.getElementById("all-hidden-note");
    if (note) note.style.display = anyVisible ? "none" : "block";
  }
  window.toggleTier = function (chip) {
    var t = chip.getAttribute("data-tier");
    if (activeTiers.has(t)) activeTiers.delete(t); else activeTiers.add(t);
    saveSet(FILTER_KEY, activeTiers);
    applyTierFilter();
  };

  function updateBar() {
    var bar = document.getElementById("selection-bar");
    document.getElementById("selection-count").textContent = String(selected.size);
    bar.classList.toggle("visible", selected.size > 0);
  }
  window.onCheck = function (el) {
    var key = el.getAttribute("data-key");
    if (el.checked) selected.add(key); else selected.delete(key);
    saveSet(SELECT_KEY, selected);
    updateBar();
  };
  window.abrirSelecionadas = function () {
    document.querySelectorAll('input[type="checkbox"][data-key]:checked').forEach(function (cb) {
      window.open(cb.getAttribute("data-url"), "_blank", "noopener");
    });
  };
  window.limparSelecao = function () {
    selected.clear();
    saveSet(SELECT_KEY, selected);
    document.querySelectorAll('input[type="checkbox"][data-key]').forEach(function (cb) { cb.checked = false; });
    updateBar();
  };

  function showToast(msg) {
    var t = document.getElementById("toast");
    t.textContent = msg;
    t.classList.add("visible");
    setTimeout(function () { t.classList.remove("visible"); }, 2600);
  }

  window.verificarVaga = function (btn, url) {
    var box = btn.closest(".action-row").nextElementSibling;
    btn.disabled = true;
    btn.textContent = "Verificando...";
    fetch("/api/check", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: url}),
    }).then(function (r) { return r.json(); }).then(function (data) {
      box.textContent = data.summary || data.error || "Sem resposta.";
      box.classList.add("visible");
    }).catch(function (e) {
      box.textContent = "Erro: " + e;
      box.classList.add("visible");
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = "Verificar";
    });
  };

  window.continuarCandidatura = function (btn, url) {
    if (!confirm("Isso vai preencher de verdade as perguntas dessa vaga com os dados do seu perfil local (RG/CPF/salário/estado civil) e, se todas baterem, ENVIAR a candidatura de verdade -- ação definitiva, não dá pra desfazer. Continuar?")) {
      return;
    }
    var box = btn.closest(".action-row").nextElementSibling;
    btn.disabled = true;
    btn.textContent = "Enviando...";
    fetch("/api/apply", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: url}),
    }).then(function (r) { return r.json(); }).then(function (data) {
      box.textContent = data.summary || data.error || "Sem resposta.";
      box.classList.add("visible");
    }).catch(function (e) {
      box.textContent = "Erro: " + e;
      box.classList.add("visible");
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = "Enviar candidatura";
    });
  };

  window.refreshVagas = function () {
    var btn = document.getElementById("refresh-btn");
    var status = document.getElementById("refresh-status");
    btn.disabled = true;
    status.textContent = "Buscando de novo (pode levar alguns minutos)...";
    fetch("/api/refresh", {method: "POST"}).then(function (r) { return r.json(); }).then(function (data) {
      status.textContent = "Pronto -- recarregando...";
      window.location.reload();
    }).catch(function (e) {
      status.textContent = "Erro: " + e;
      btn.disabled = false;
    });
  };

  window.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('input[type="checkbox"][data-key]').forEach(function (cb) {
      if (selected.has(cb.getAttribute("data-key"))) cb.checked = true;
    });
    updateBar();
    applyTierFilter();
  });
})();
