/* Ground Lite × OpenClaw sidebar assistant */
(function () {
  const API = "/api/ai";
  const LS_KEY = "gl_oc_messages";
  const LS_MODEL = "gl_oc_model";

  function $(id) { return document.getElementById(id); }
  function loadMsgs() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || "[]"); } catch { return []; }
  }
  function saveMsgs(msgs) { localStorage.setItem(LS_KEY, JSON.stringify(msgs.slice(-80))); }
  function getModel() { return localStorage.getItem(LS_MODEL) || ""; }
  function setModel(m) {
    if (m) localStorage.setItem(LS_MODEL, m);
    else localStorage.removeItem(LS_MODEL);
  }

  function fmtTs(ts) {
    if (!ts) return "";
    const d = new Date(ts);
    if (isNaN(d.getTime())) return "";
    const p = (n) => String(n).padStart(2, "0");
    return (
      d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds())
    );
  }

  function render() {
    const msgs = $("aiMsgs");
    if (!msgs) return;
    msgs.innerHTML = "";
    const data = loadMsgs();
    if (!data.length) {
      const d = document.createElement("div");
      d.className = "ai-empty";
      d.textContent = "OpenClaw 域感助理已就绪。可在上方选择云端/本地模型。可问：最近任务、盘点差异、货架绑定、无人机状态。";
      msgs.appendChild(d);
      return;
    }
    for (const m of data) {
      const row = document.createElement("div");
      row.className = "ai-msg " + (m.role === "user" ? "ai-user" : "ai-bot");
      const b = document.createElement("div");
      b.className = "ai-bubble";
      b.textContent = m.text;
      row.appendChild(b);

      const meta = document.createElement("div");
      meta.className = "ai-meta";
      const parts = [];
      if (m.ts) parts.push(fmtTs(m.ts));
      if (m.meta) parts.push(m.meta);
      if (m.pending) parts.push("生成中…");
      meta.textContent = parts.join(" · ");
      row.appendChild(meta);
      msgs.appendChild(row);
    }
    msgs.scrollTop = msgs.scrollHeight;
  }

  async function loadModels() {
    const sel = $("aiModelSelect");
    if (!sel) return;
    try {
      const r = await fetch(API + "/models");
      const j = await r.json();
      const current = getModel() || j.default || "";
      sel.innerHTML = "";

      function addGroup(label, items, groupKey) {
        if (!items || !items.length) return;
        const og = document.createElement("optgroup");
        og.label = label;
        for (const m of items) {
          const opt = document.createElement("option");
          opt.value = m.id;
          opt.textContent = m.label || m.id;
          opt.setAttribute("data-group", groupKey);
          if (m.id === current) opt.selected = true;
          og.appendChild(opt);
        }
        sel.appendChild(og);
      }

      const groups = j.groups || {};
      if (groups.cloud || groups.local) {
        addGroup((groups.cloud && groups.cloud.label) || "云端模型", groups.cloud && groups.cloud.items, "cloud");
        addGroup((groups.local && groups.local.label) || "本地模型", groups.local && groups.local.items, "local");
      } else {
        addGroup("模型", j.models || [], "local");
      }
      if (current && sel.value !== current) {
        const exists = Array.from(sel.options).some((o) => o.value === current);
        if (exists) sel.value = current;
      }
      if (!sel.value && sel.options.length) sel.value = sel.options[0].value;
    } catch (e) {
      sel.innerHTML = "";
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "模型列表加载失败";
      sel.appendChild(opt);
    }
  }

  function setBusy(busy) {
    const sendBtn = $("aiSend");
    const sel = $("aiModelSelect");
    const status = $("aiStatus");
    if (sendBtn) sendBtn.disabled = !!busy;
    // Lock model while a turn is in flight so the answer label stays honest
    if (sel) sel.disabled = !!busy;
    if (busy && status) status.textContent = "思考中…（模型已锁定本次回答）";
  }

  async function ask(q) {
    const text = (q || "").trim();
    if (!text) return;
    const input = $("aiText");
    const status = $("aiStatus");
    const sel = $("aiModelSelect");
    const model = (sel && sel.value) || getModel() || "";
    setModel(model);

    const now = Date.now();
    const data = loadMsgs();
    data.push({ role: "user", text, ts: now });
    data.push({ role: "bot", text: "……", ts: now, pending: true, meta: (model ? "使用 " + model : "") });
    saveMsgs(data);
    render();
    setBusy(true);

    try {
      const r = await fetch(API + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, model }),
      });
      const j = await r.json();
      const answer = j.answer || j.error || "（无回答）";
      const data2 = loadMsgs();
      // replace last pending bot message
      for (let i = data2.length - 1; i >= 0; i--) {
        if (data2[i].role === "bot" && data2[i].pending) {
          data2[i] = {
            role: "bot",
            text: answer,
            ts: Date.now(),
            meta: (j.engine === "openclaw" ? "OpenClaw" : j.engine || "") + (j.model ? " · " + j.model : ""),
          };
          break;
        }
      }
      saveMsgs(data2);
      if (status) status.textContent = j.ok ? "就绪 · " + (j.model || j.engine || "openclaw") : "出错";
    } catch (e) {
      const data2 = loadMsgs();
      for (let i = data2.length - 1; i >= 0; i--) {
        if (data2[i].role === "bot" && data2[i].pending) {
          data2[i] = { role: "bot", text: "请求失败：" + e.message, ts: Date.now() };
          break;
        }
      }
      saveMsgs(data2);
      if (status) status.textContent = "连接失败";
    } finally {
      setBusy(false);
      render();
      if (input) input.focus();
    }
  }

  function bind() {
    const form = $("aiForm");
    if (!form || form.dataset.bound) return;
    form.dataset.bound = "1";
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("aiText");
      const v = input.value;
      input.value = "";
      ask(v);
    });
    const chips = $("aiChips");
    if (chips) {
      chips.addEventListener("click", (e) => {
        const b = e.target.closest("button[data-q]");
        if (b) ask(b.getAttribute("data-q"));
      });
    }
    const clear = $("aiClear");
    if (clear) {
      clear.addEventListener("click", () => {
        saveMsgs([]);
        render();
      });
    }
    const sel = $("aiModelSelect");
    if (sel) {
      sel.addEventListener("change", () => {
        if (sel.disabled) return;
        setModel(sel.value);
        const status = $("aiStatus");
        if (status) {
          const opt = sel.selectedOptions[0];
          status.textContent = "已选择：" + (opt ? opt.textContent : sel.value) + "（对下一条生效）";
        }
      });
    }
    loadModels();
    fetch(API + "/health")
      .then((r) => r.json())
      .then((j) => {
        const status = $("aiStatus");
        if (!status) return;
        if (j.engines && j.engines.openclaw && j.engines.openclaw.ok) status.textContent = "OpenClaw 在线";
        else if (j.engines && j.engines.ollama && j.engines.ollama.ok) status.textContent = "Ollama 兜底";
        else status.textContent = "AI 引擎未就绪";
      })
      .catch(() => {
        const status = $("aiStatus");
        if (status) status.textContent = "后端未就绪";
      });
    render();
  }

  window.openAiAssistant = function () {
    bind();
    render();
    const input = $("aiText");
    if (input) setTimeout(() => input.focus(), 80);
  };

  const _switchPage = window.switchPage;
  window.switchPage = function (page) {
    if (typeof _switchPage === "function") _switchPage(page);
    if (page === "assistant") {
      const t = $("pageTitle");
      if (t) t.textContent = "AI 助理";
      bind();
      render();
      loadModels();
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      bind();
      document.querySelectorAll('.nav-item[data-page="assistant"]').forEach((btn) => {
        btn.addEventListener("click", () => setTimeout(bind, 10));
      });
    });
  } else {
    bind();
    document.querySelectorAll('.nav-item[data-page="assistant"]').forEach((btn) => {
      btn.addEventListener("click", () => setTimeout(bind, 10));
    });
  }
})();
