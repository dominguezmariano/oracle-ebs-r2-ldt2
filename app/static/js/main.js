// R2-LDT2 — main.js

document.addEventListener("DOMContentLoaded", () => {
  // Submenu toggle
  document.querySelectorAll(".nav-toggle").forEach(el => {
    el.addEventListener("click", e => {
      e.preventDefault();
      const sub = document.querySelector(el.dataset.target);
      if (sub) sub.classList.toggle("open");
      el.classList.toggle("open");
    });
  });

  // Auto-open submenu if a child is active
  document.querySelectorAll(".r2-submenu").forEach(sub => {
    if (sub.querySelector("a.active")) {
      sub.classList.add("open");
      const toggle = document.querySelector(`[data-target="#${sub.id}"]`);
      if (toggle) toggle.classList.add("open");
    }
  });

  // Flash auto-dismiss
  document.querySelectorAll(".r2-alert[data-dismiss]").forEach(el => {
    setTimeout(() => el.remove(), 4000);
  });

  // Copy to clipboard
  document.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const code = btn.closest(".r2-code").querySelector("code, span, pre");
      const text = code ? code.textContent : btn.closest(".r2-code").textContent.trim();
      navigator.clipboard.writeText(text).then(() => {
        const orig = btn.textContent;
        btn.textContent = "Copiado!";
        setTimeout(() => (btn.textContent = orig), 1500);
      });
    });
  });

  // Confirm delete
  document.querySelectorAll("form[data-confirm]").forEach(form => {
    form.addEventListener("submit", e => {
      if (!confirm(form.dataset.confirm)) e.preventDefault();
    });
  });
});

// Test DB connection (Download Manager / Ambientes)
function testConexion(ambienteId, user, pass) {
  fetch(`/configuracion/ambientes/${ambienteId}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `test_user=${encodeURIComponent(user)}&test_pass=${encodeURIComponent(pass)}`,
  })
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById("test-result");
      if (el) {
        el.className = `r2-alert ${data.ok ? "success" : "danger"}`;
        el.textContent = data.message;
        el.style.display = "flex";
      }
    });
}

// Generate FNDLOAD sentence
function generarSentencia() {
  const form = document.getElementById("gen-form");
  if (!form) return;
  const data = new URLSearchParams(new FormData(form));
  fetch("/download/generar", { method: "POST", body: data })
    .then(r => r.json())
    .then(res => {
      const out = document.getElementById("sentencia-output");
      if (!out) return;
      if (res.ok) {
        out.querySelector("span").textContent = res.sentencia;
        out.style.display = "block";
      } else {
        alert("Error: " + res.error);
      }
    });
}
