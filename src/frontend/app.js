(() => {
  const state = {
    runId: "",
    since: 0,
    pollingTimer: null,
  };

  const els = {
    startForm: document.getElementById("start-form"),
    taskId: document.getElementById("task-id"),
    taskPrompt: document.getElementById("task-prompt"),
    mode: document.getElementById("mode"),
    runIdLine: document.getElementById("run-id-line"),
    status: document.getElementById("status"),
    window: document.getElementById("window"),
    round: document.getElementById("round"),
    step: document.getElementById("step"),
    operatorForm: document.getElementById("operator-form"),
    operatorId: document.getElementById("operator-id"),
    operatorText: document.getElementById("operator-text"),
    logList: document.getElementById("log-list"),
    reportBtn: document.getElementById("report-btn"),
    reportBox: document.getElementById("report-box"),
  };

  async function request(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }
    return response.json();
  }

  function pushLog(event) {
    const item = document.createElement("li");
    item.className = "log-item";
    item.dataset.type = event.event_type;
    const bodyText = [
      event.command_text ? `input: ${event.command_text}` : "",
      event.model_output_text ? `output: ${event.model_output_text}` : "",
      event.meta && Object.keys(event.meta).length ? `meta: ${JSON.stringify(event.meta)}` : "",
    ]
      .filter(Boolean)
      .join("\n");

    item.innerHTML = `
      <div class="log-head">
        <strong>${event.event_type}</strong>
        <span>w${event.window_index} r${event.round_index_in_window} g${event.global_round_index}</span>
      </div>
      <pre class="log-body">${bodyText || "-"}</pre>
    `;
    els.logList.prepend(item);
  }

  function renderSnapshot(snapshot) {
    els.status.textContent = snapshot.status || "-";
    els.window.textContent = `${snapshot.current_window_index || "-"} / ${snapshot.current_window_id || "-"}`;
    els.round.textContent = `${snapshot.current_round_index_in_window || "-"}`;
    els.step.textContent = snapshot.current_step_id || "-";
  }

  async function pollOnce() {
    if (!state.runId) return;
    const snapshot = await request(`/api/runs/${state.runId}`);
    renderSnapshot(snapshot);

    const evResp = await request(`/api/runs/${state.runId}/events?since=${state.since}`);
    const events = evResp.events || [];
    events.forEach(pushLog);
    state.since = evResp.next_since || state.since;

    if (["completed", "failed", "stopped"].includes(snapshot.status)) {
      stopPolling();
    }
  }

  function stopPolling() {
    if (state.pollingTimer) {
      clearInterval(state.pollingTimer);
      state.pollingTimer = null;
    }
  }

  function startPolling() {
    stopPolling();
    state.pollingTimer = setInterval(() => {
      pollOnce().catch((error) => {
        stopPolling();
        alert(`轮询失败: ${error.message}`);
      });
    }, 1000);
    pollOnce().catch((error) => {
      alert(`拉取失败: ${error.message}`);
    });
  }

  els.startForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    els.logList.innerHTML = "";
    els.reportBox.textContent = "";
    state.since = 0;
    const payload = {
      task_id: els.taskId.value.trim() || "session-task",
      task_prompt: els.taskPrompt.value.trim(),
      mode: els.mode.value,
    };
    const created = await request("/api/runs/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.runId = created.run_id;
    els.runIdLine.textContent = `run_id: ${state.runId}`;
    startPolling();
  });

  els.operatorForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.runId) {
      alert("请先启动运行");
      return;
    }
    await request(`/api/runs/${state.runId}/operator-message`, {
      method: "POST",
      body: JSON.stringify({
        operator_id: els.operatorId.value.trim() || "human",
        text: els.operatorText.value.trim(),
      }),
    });
    els.operatorText.value = "";
    await pollOnce();
  });

  els.reportBtn.addEventListener("click", async () => {
    if (!state.runId) {
      alert("请先启动运行");
      return;
    }
    const report = await request(`/api/runs/${state.runId}/report`);
    els.reportBox.textContent = report.report_markdown || "";
  });
})();
