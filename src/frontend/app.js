(() => {
  const state = {
    runId: "",
    status: "",
    since: 0,
    pollingTimer: null,
    rounds: new Map(),
  };

  const els = {
    setupView: document.getElementById("setup-view"),
    chatView: document.getElementById("chat-view"),
    startForm: document.getElementById("start-form"),
    taskId: document.getElementById("task-id"),
    workspaceProjectRoot: document.getElementById("workspace-project-root"),
    gitScopePath: document.getElementById("git-scope-path"),
    taskPrompt: document.getElementById("task-prompt"),
    mode: document.getElementById("mode"),
    runIdLine: document.getElementById("run-id-line"),
    status: document.getElementById("status"),
    window: document.getElementById("window"),
    round: document.getElementById("round"),
    step: document.getElementById("step"),
    conversation: document.getElementById("conversation"),
    operatorForm: document.getElementById("operator-form"),
    operatorId: document.getElementById("operator-id"),
    operatorText: document.getElementById("operator-text"),
    reportBtn: document.getElementById("report-btn"),
    reportBox: document.getElementById("report-box"),
    restartBtn: document.getElementById("restart-btn"),
    globalAlert: document.getElementById("global-alert"),
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

  function showAlert(message) {
    if (!els.globalAlert) return;
    els.globalAlert.textContent = message;
    window.clearTimeout(showAlert.timer);
    showAlert.timer = window.setTimeout(() => {
      els.globalAlert.textContent = "";
    }, 3500);
  }

  function formatTime(isoTime) {
    if (!isoTime) return "--:--:--";
    const date = new Date(isoTime);
    if (Number.isNaN(date.getTime())) return "--:--:--";
    return date.toLocaleTimeString("zh-CN", { hour12: false });
  }

  function escapeHtml(raw) {
    const text = String(raw ?? "");
    return text
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function setViewMode(mode) {
    const isChat = mode === "chat";
    els.setupView.classList.toggle("is-hidden", isChat);
    els.chatView.classList.toggle("is-hidden", !isChat);
  }

  function updateStatusBadge(statusText) {
    els.status.dataset.state = statusText || "";
  }

  function resetSessionView() {
    state.rounds.clear();
    els.conversation.innerHTML = "";
    els.reportBox.textContent = "";
  }

  function appendSystemEvent(event, summary) {
    const row = document.createElement("article");
    row.className = "system-event";
    row.innerHTML = `
      <span class="system-time">${formatTime(event.timestamp)}</span>
      <strong>${escapeHtml(summary)}</strong>
    `;
    els.conversation.appendChild(row);
  }

  function ensureRoundCard(event) {
    const roundId = Number(event.global_round_index || 0);
    if (!roundId) return null;

    if (state.rounds.has(roundId)) {
      return state.rounds.get(roundId);
    }

    const card = document.createElement("article");
    card.className = "round-card";
    card.innerHTML = `
      <header class="round-head">
        <div>
          <h3 class="round-title">第 ${roundId} 轮</h3>
          <p class="round-sub">窗口 w${event.window_index} · 窗口轮次 r${event.round_index_in_window}</p>
        </div>
        <span class="round-tag pending">进行中</span>
      </header>
      <section class="round-bubble input">
        <span class="bubble-label">输入</span>
        <pre class="bubble-body">-</pre>
      </section>
      <section class="round-bubble output">
        <span class="bubble-label">输出</span>
        <pre class="bubble-body">-</pre>
      </section>
      <p class="round-foot">step: ${escapeHtml(event.step_id || "-")} · 最近事件: ${escapeHtml(event.event_type || "-")}</p>
    `;
    els.conversation.appendChild(card);

    const data = {
      card,
      tag: card.querySelector(".round-tag"),
      input: card.querySelector(".round-bubble.input .bubble-body"),
      output: card.querySelector(".round-bubble.output .bubble-body"),
      foot: card.querySelector(".round-foot"),
    };
    state.rounds.set(roundId, data);
    return data;
  }

  function updateRoundFromEvent(event) {
    const round = ensureRoundCard(event);
    if (!round) return;
    const eventType = event.event_type || "";
    const stepName = event.meta && event.meta.step_name ? String(event.meta.step_name) : "";
    const foot = `step: ${event.step_id || "-"} · 最近事件: ${eventType} · ${formatTime(event.timestamp)}`;
    round.foot.textContent = foot;

    if ((eventType === "step_started" || eventType === "model_input") && event.command_text) {
      round.input.textContent = event.command_text;
    }

    if ((eventType === "model_output" || eventType === "step_finished") && event.model_output_text) {
      round.output.textContent = event.model_output_text;
    }

    if (eventType === "model_output" && !event.model_output_text) {
      round.output.textContent = "-";
    }

    if (eventType === "step_finished") {
      const stepStatus = event.meta && event.meta.step_status ? String(event.meta.step_status) : "";
      round.tag.textContent = stepStatus === "failed" ? "失败" : "完成";
      round.tag.className = `round-tag ${stepStatus === "failed" ? "failed" : "passed"}`;
      if (stepName) {
        round.foot.textContent = `${foot} · ${stepName}`;
      }
    }

    if (eventType === "step_retrying") {
      round.tag.textContent = "重试中";
      round.tag.className = "round-tag retrying";
    }

    if (eventType === "error") {
      round.tag.textContent = "异常";
      round.tag.className = "round-tag failed";
      const errorText = event.meta && event.meta.error ? String(event.meta.error) : "运行发生异常";
      round.output.textContent = errorText;
    }
  }

  function scrollConversationToBottom() {
    const node = els.conversation;
    if (!node) return;

    const apply = () => {
      node.scrollTop = node.scrollHeight;
      window.scrollTo({
        top: document.body.scrollHeight,
        behavior: "instant",
      });
    };
    apply();
    window.requestAnimationFrame(apply);
    window.setTimeout(apply, 0);
  }

  function renderEvent(event) {
    const roundId = Number(event.global_round_index || 0);
    if (roundId > 0) {
      updateRoundFromEvent(event);
      scrollConversationToBottom();
      return;
    }
    if (event.event_type === "window_started") {
      appendSystemEvent(event, "新窗口已启动");
      scrollConversationToBottom();
      return;
    }
    if (event.event_type === "window_closed") {
      appendSystemEvent(event, "窗口已关闭");
      scrollConversationToBottom();
      return;
    }
    if (event.event_type === "interrupted") {
      appendSystemEvent(event, "运行被人工中断，等待进一步输入");
      scrollConversationToBottom();
    }
  }

  function renderSnapshot(snapshot) {
    const statusText = snapshot.status || "-";
    state.status = statusText;
    els.status.textContent = statusText;
    updateStatusBadge(statusText);
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
    events.forEach(renderEvent);
    if (events.length > 0) {
      scrollConversationToBottom();
    }
    state.since = evResp.next_since || state.since;

    if (["completed", "failed", "stopped"].includes(snapshot.status)) {
      stopPolling();
      appendSystemEvent(
        { timestamp: snapshot.updated_at },
        `运行结束：${snapshot.status || "unknown"}`,
      );
      scrollConversationToBottom();
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
        showAlert(`轮询失败: ${error.message}`);
      });
    }, 320);
    pollOnce().catch((error) => {
      showAlert(`拉取失败: ${error.message}`);
    });
  }

  els.startForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      resetSessionView();
      state.since = 0;
      const payload = {
        task_id: els.taskId.value.trim() || "session-task",
        workspace_project_root: els.workspaceProjectRoot.value.trim() || "",
        git_scope_path: els.gitScopePath.value.trim() || "",
        task_prompt: els.taskPrompt.value.trim(),
        mode: els.mode.value,
        step_delay_seconds: els.mode.value === "mock" ? 0.35 : 0,
      };
      const created = await request("/api/runs/start", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.runId = created.run_id;
      els.runIdLine.textContent = `run_id: ${state.runId}`;
      setViewMode("chat");
      appendSystemEvent({ timestamp: new Date().toISOString() }, "已启动任务，开始拉取实时日志");
      startPolling();
    } catch (error) {
      showAlert(`启动失败: ${error.message}`);
      setViewMode("setup");
    }
  });

  els.operatorForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.runId) {
      showAlert("请先启动运行");
      return;
    }
    if (!["running", "paused"].includes(state.status)) {
      showAlert("当前运行已结束，请点击“新建运行”");
      return;
    }
    const text = els.operatorText.value.trim();
    if (!text) {
      showAlert("请输入消息内容");
      return;
    }
    try {
      await request(`/api/runs/${state.runId}/operator-message`, {
        method: "POST",
        body: JSON.stringify({
          operator_id: els.operatorId.value.trim() || "human",
          text,
        }),
      });
      appendSystemEvent(
        { timestamp: new Date().toISOString() },
        `人工消息已发送: ${text}`,
      );
      els.operatorText.value = "";
      scrollConversationToBottom();
      await pollOnce();
    } catch (error) {
      showAlert(`发送失败: ${error.message}`);
    }
  });

  els.reportBtn.addEventListener("click", async () => {
    if (!state.runId) {
      showAlert("请先启动运行");
      return;
    }
    try {
      const report = await request(`/api/runs/${state.runId}/report`);
      els.reportBox.textContent = report.report_markdown || "";
    } catch (error) {
      showAlert(`报告生成失败: ${error.message}`);
    }
  });

  els.restartBtn.addEventListener("click", () => {
    stopPolling();
    state.runId = "";
    state.status = "";
    state.since = 0;
    resetSessionView();
    renderSnapshot({
      status: "-",
      current_window_index: "-",
      current_window_id: "-",
      current_round_index_in_window: "-",
      current_step_id: "-",
    });
    setViewMode("setup");
  });
})();
