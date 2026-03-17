(() => {
  const state = {
    runId: "",
    status: "idle",
    phase: "",
    workflowMode: "work_items",
    pauseReason: "",
    currentWorkItemId: "",
    since: 0,
    pollingTimer: null,
    pollingInFlight: false,
    pollingQueued: false,
  };

  const terminalStatuses = new Set(["completed", "failed", "stopped"]);

  const els = {
    taskId: document.getElementById("task-id"),
    workspaceProjectRoot: document.getElementById("workspace-project-root"),
    gitScopePath: document.getElementById("git-scope-path"),
    mode: document.getElementById("mode"),
    workflowMode: document.getElementById("workflow-mode"),
    operatorId: document.getElementById("operator-id"),
    restartBtn: document.getElementById("restart-btn"),
    reportBtn: document.getElementById("report-btn"),
    reportBox: document.getElementById("report-box"),
    runIdLine: document.getElementById("run-id-line"),
    status: document.getElementById("status"),
    phase: document.getElementById("phase"),
    window: document.getElementById("window"),
    round: document.getElementById("round"),
    step: document.getElementById("step"),
    statusBadge: document.getElementById("status-badge"),
    chatForm: document.getElementById("chat-form"),
    chatInput: document.getElementById("chat-input"),
    conversation: document.getElementById("conversation"),
    globalAlert: document.getElementById("global-alert"),
    workItemCurrentBox: document.getElementById("workitem-current-box"),
    workItemList: document.getElementById("workitem-list"),
    reviewStatus: document.getElementById("review-status"),
    commandReviewBox: document.getElementById("command-review-box"),
    humanReviewNote: document.getElementById("human-review-note"),
    approveBtn: document.getElementById("approve-btn"),
    rejectBtn: document.getElementById("reject-btn"),
    pauseBtn: document.getElementById("pause-btn"),
    resumeBtn: document.getElementById("resume-btn"),
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
    if (!els.globalAlert) {
      return;
    }
    els.globalAlert.textContent = message;
    window.clearTimeout(showAlert.timer);
    showAlert.timer = window.setTimeout(() => {
      els.globalAlert.textContent = "";
    }, 3800);
  }

  function formatTime(isoTime) {
    if (!isoTime) {
      return "--:--:--";
    }
    const date = new Date(isoTime);
    if (Number.isNaN(date.getTime())) {
      return "--:--:--";
    }
    return date.toLocaleTimeString("zh-CN", { hour12: false });
  }

  function toText(value) {
    return String(value ?? "").trim();
  }

  function scrollToBottom() {
    els.conversation.scrollTop = els.conversation.scrollHeight;
  }

  function appendMessage({ role, text, time = "", note = "" }) {
    const bodyText = toText(text);
    if (!bodyText) {
      return;
    }

    const row = document.createElement("article");
    row.className = `msg msg-${role}`;

    const head = document.createElement("header");
    head.className = "msg-head";

    const roleNode = document.createElement("strong");
    roleNode.className = "msg-role";
    roleNode.textContent =
      role === "user"
        ? "你"
        : role === "assistant"
        ? "助手"
        : "系统";

    const timeNode = document.createElement("span");
    timeNode.className = "msg-time";
    timeNode.textContent = formatTime(time);

    head.appendChild(roleNode);
    head.appendChild(timeNode);

    const body = document.createElement("pre");
    body.className = "msg-body";
    body.textContent = bodyText;

    row.appendChild(head);
    row.appendChild(body);

    if (toText(note)) {
      const foot = document.createElement("footer");
      foot.className = "msg-note";
      foot.textContent = note;
      row.appendChild(foot);
    }

    els.conversation.appendChild(row);
    scrollToBottom();
  }

  function updateStatusBadge(statusText) {
    const normalized = toText(statusText).toUpperCase() || "IDLE";
    els.statusBadge.textContent = normalized;
    els.statusBadge.dataset.state = toText(statusText);
  }

  function renderSnapshot(snapshot) {
    const statusText = toText(snapshot.status) || "idle";
    state.status = statusText;
    state.phase = toText(snapshot.phase);
    state.workflowMode = toText(snapshot.workflow_mode) || state.workflowMode;
    state.pauseReason = toText(snapshot.pause_reason);
    state.currentWorkItemId = toText(snapshot.current_work_item_id);
    els.status.textContent = statusText;
    if (els.phase) {
      els.phase.textContent = state.phase || "-";
    }
    els.window.textContent = `${snapshot.current_window_index ?? "-"} / ${snapshot.current_window_id ?? "-"}`;
    els.round.textContent = `${snapshot.current_round_index_in_window ?? "-"}`;
    els.step.textContent = toText(snapshot.current_workflow_step || snapshot.current_step_id) || "-";
    els.runIdLine.textContent = `run_id: ${state.runId || "-"}`;
    updateStatusBadge(statusText);
  }

  function resetState() {
    stopPolling();
    state.runId = "";
    state.status = "idle";
    state.phase = "";
    state.pauseReason = "";
    state.currentWorkItemId = "";
    state.since = 0;

    els.runIdLine.textContent = "run_id: -";
    els.status.textContent = "idle";
    if (els.phase) {
      els.phase.textContent = "-";
    }
    els.window.textContent = "-";
    els.round.textContent = "-";
    els.step.textContent = "-";
    updateStatusBadge("idle");

    els.reportBox.textContent = "";
    els.conversation.innerHTML = "";
    if (els.workItemList) {
      els.workItemList.innerHTML = "";
    }
    if (els.workItemCurrentBox) {
      els.workItemCurrentBox.textContent = "";
    }
    if (els.reviewStatus) {
      els.reviewStatus.textContent = "";
    }
    if (els.commandReviewBox) {
      els.commandReviewBox.textContent = "";
    }
    if (els.humanReviewNote) {
      els.humanReviewNote.value = "";
    }
  }

  function summarizePolicy(meta) {
    const decisionResult = toText(meta.decision_result) || "continue_same_window";
    const reason = toText(meta.reason) || "-";
    const action = toText(meta.action) || "-";
    return `策略决策：${decisionResult}（action=${action}, reason=${reason}）`;
  }

  function renderEvent(event) {
    const eventType = toText(event.event_type);
    const time = toText(event.timestamp);
    const meta = event.meta && typeof event.meta === "object" ? event.meta : {};
    const stepName = toText(meta.step_name);

    if (eventType === "model_output") {
      appendMessage({
        role: "assistant",
        text: event.model_output_text,
        time,
        note: stepName ? `步骤：${stepName}` : "",
      });
      return;
    }

    if (eventType === "error") {
      appendMessage({
        role: "system",
        text: `运行异常：${toText(meta.error) || "未知错误"}`,
        time,
      });
      return;
    }

    if (eventType === "window_started") {
      appendMessage({ role: "system", text: "已启动新窗口。", time });
      return;
    }

    if (eventType === "window_closed") {
      appendMessage({
        role: "system",
        text: `窗口已关闭（reason=${toText(meta.reason) || "-"}）。`,
        time,
      });
      return;
    }

    if (eventType === "step_started") {
      appendMessage({
        role: "system",
        text: `开始执行步骤：${stepName || "task_prompt"}`,
        time,
      });
      return;
    }

    if (eventType === "step_retrying") {
      appendMessage({
        role: "system",
        text: `步骤重试：${stepName || "-"}（failure=${toText(meta.failure_code) || "-"}）`,
        time,
      });
      return;
    }

    if (eventType === "policy_decision") {
      appendMessage({
        role: "system",
        text: summarizePolicy(meta),
        time,
      });
      return;
    }

    if (eventType === "interrupted") {
      appendMessage({
        role: "system",
        text: "当前运行已被人工消息打断。",
        time,
      });
    }
  }

  function clearWorkItemPanels() {
    if (els.workItemList) {
      els.workItemList.innerHTML = "";
    }
    if (els.workItemCurrentBox) {
      els.workItemCurrentBox.textContent = "";
    }
    if (els.reviewStatus) {
      els.reviewStatus.textContent = "";
    }
    if (els.commandReviewBox) {
      els.commandReviewBox.textContent = "";
    }
  }

  function renderWorkItems(payload) {
    const workItems = Array.isArray(payload.work_items) ? payload.work_items : [];
    const currentId = toText(payload.current_work_item_id);
    const current =
      payload.current_item && typeof payload.current_item === "object"
        ? payload.current_item
        : null;

    state.currentWorkItemId = currentId;

    if (els.workItemCurrentBox) {
      const lines = [];
      lines.push(`goal: ${toText(payload.goal) || "-"}`);
      lines.push(`phase: ${toText(payload.phase) || "-"}`);
      lines.push(`current_work_item_id: ${currentId || "-"}`);
      if (current) {
        lines.push(`title: ${toText(current.title) || "-"}`);
        lines.push(`status: ${toText(current.status) || "-"}`);
        lines.push(`scope: ${toText(current.scope_path) || "-"}`);
        const required = Number(current.review_required || 0);
        const passed = Number(current.review_passed || 0);
        if (required) {
          lines.push(`review: ${passed}/${required}`);
        }
        const acceptance = Array.isArray(current.acceptance) ? current.acceptance : [];
        if (acceptance.length) {
          lines.push("acceptance:");
          for (const item of acceptance.slice(0, 10)) {
            lines.push(`- ${toText(item)}`);
          }
        }
      }
      els.workItemCurrentBox.textContent = lines.join("\n").trim();
    }

    if (els.workItemList) {
      els.workItemList.innerHTML = "";
      for (const item of workItems) {
        if (!item || typeof item !== "object") {
          continue;
        }
        const li = document.createElement("li");
        const itemId = toText(item.id);
        li.dataset.current = itemId && itemId === currentId ? "true" : "false";
        li.dataset.status = toText(item.status);

        const title = document.createElement("div");
        title.className = "workitem-title";
        title.textContent = toText(item.title) || itemId || "未命名 WorkItem";

        const meta = document.createElement("div");
        meta.className = "workitem-meta";
        meta.textContent = `id=${itemId || "-"} root=${toText(item.root_id) || "-"} scope=${toText(item.scope_path) || "-"}`;

        const status = document.createElement("div");
        status.className = "workitem-status";
        const required = Number(item.review_required || 0);
        const passed = Number(item.review_passed || 0);
        status.textContent = `status=${toText(item.status) || "-"} review=${passed}/${required}`;

        li.appendChild(title);
        li.appendChild(meta);
        li.appendChild(status);
        els.workItemList.appendChild(li);
      }
    }

    const canHumanReview =
      state.runId &&
      state.status === "paused" &&
      state.pauseReason === "human_review" &&
      currentId;

    if (els.reviewStatus) {
      const hint = canHumanReview
        ? "当前等待人工评审：请选择通过或打回"
        : state.pauseReason
        ? `pause_reason: ${state.pauseReason}`
        : "";
      els.reviewStatus.textContent = hint;
    }

    if (els.commandReviewBox) {
      const review = current && current.last_command_review ? current.last_command_review : null;
      els.commandReviewBox.textContent = review && toText(review.summary) ? toText(review.summary) : "";
    }

    if (els.approveBtn) {
      els.approveBtn.disabled = !canHumanReview;
    }
    if (els.rejectBtn) {
      els.rejectBtn.disabled = !canHumanReview;
    }
    if (els.pauseBtn) {
      els.pauseBtn.disabled = !state.runId || terminalStatuses.has(state.status);
    }
    if (els.resumeBtn) {
      els.resumeBtn.disabled = !state.runId || state.status !== "paused";
    }
  }

  async function pollOnce() {
    const runId = state.runId;
    if (!runId) {
      return;
    }

    if (state.pollingInFlight) {
      state.pollingQueued = true;
      return;
    }

    state.pollingInFlight = true;
    state.pollingQueued = false;
    const since = state.since;

    try {
      const snapshot = await request(`/api/runs/${runId}`);
      if (state.runId !== runId) {
        return;
      }
      renderSnapshot(snapshot);

      if (toText(snapshot.workflow_mode) === "work_items") {
        const workItemsPayload = await request(`/api/runs/${runId}/work-items`);
        if (state.runId !== runId) {
          return;
        }
        renderWorkItems(workItemsPayload);
      } else {
        clearWorkItemPanels();
      }

      const evResp = await request(`/api/runs/${runId}/events?since=${since}`);
      if (state.runId !== runId) {
        return;
      }
      const events = Array.isArray(evResp.events) ? evResp.events : [];
      for (const event of events) {
        renderEvent(event);
      }
      state.since = Number(evResp.next_since || since || 0);

      if (terminalStatuses.has(snapshot.status)) {
        stopPolling();
        appendMessage({
          role: "system",
          text: `运行结束：${snapshot.status}`,
          time: snapshot.updated_at,
        });
      }
    } finally {
      if (state.runId === runId) {
        state.pollingInFlight = false;
        if (state.pollingQueued && state.pollingTimer !== null) {
          state.pollingQueued = false;
          window.setTimeout(() => {
            if (state.pollingTimer === null || state.runId !== runId) {
              return;
            }
            pollOnce().catch((error) => {
              stopPolling();
              showAlert(`轮询失败: ${error.message}`);
            });
          }, 0);
        }
      }
    }
  }

  function stopPolling() {
    if (state.pollingTimer !== null) {
      window.clearInterval(state.pollingTimer);
      state.pollingTimer = null;
    }
    state.pollingInFlight = false;
    state.pollingQueued = false;
  }

  function startPolling() {
    stopPolling();
    state.pollingTimer = window.setInterval(() => {
      pollOnce().catch((error) => {
        stopPolling();
        showAlert(`轮询失败: ${error.message}`);
      });
    }, 360);

    pollOnce().catch((error) => {
      showAlert(`拉取失败: ${error.message}`);
    });
  }

  async function startRunByFirstMessage(firstPrompt) {
    const workflowMode = toText(els.workflowMode && els.workflowMode.value) || "work_items";
    const maxRounds = workflowMode === "work_items" ? 80 : 12;
    const payload = {
      task_id: toText(els.taskId.value) || "session-task",
      task_prompt: toText(firstPrompt),
      task_type: "dev",
      workflow_mode: workflowMode,
      mode: toText(els.mode.value) || "mock",
      max_rounds: maxRounds,
      max_rounds_per_window: maxRounds,
      workspace_project_root: toText(els.workspaceProjectRoot.value),
      git_scope_path: toText(els.gitScopePath.value),
      step_delay_seconds: toText(els.mode.value) === "mock" ? 0.2 : 0,
    };

    const created = await request("/api/runs/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    state.runId = toText(created.run_id);
    state.since = 0;
    els.runIdLine.textContent = `run_id: ${state.runId}`;

    appendMessage({
      role: "system",
      text: `已创建运行：${state.runId}`,
      time: new Date().toISOString(),
    });

    startPolling();
  }

  async function sendOperatorMessage(text) {
    await request(`/api/runs/${state.runId}/operator-message`, {
      method: "POST",
      body: JSON.stringify({
        operator_id: toText(els.operatorId.value) || "human",
        text,
      }),
    });
  }

  async function handleSubmitMessage(rawText) {
    const text = toText(rawText);
    if (!text) {
      showAlert("请输入消息后再发送");
      return;
    }

    appendMessage({
      role: "user",
      text,
      time: new Date().toISOString(),
    });

    const noActiveRun = !state.runId || terminalStatuses.has(state.status);
    if (noActiveRun) {
      await startRunByFirstMessage(text);
      return;
    }

    if (!new Set(["running", "paused"]).has(state.status)) {
      showAlert(`当前状态 ${state.status} 不支持插话，将自动新建运行。`);
      await startRunByFirstMessage(text);
      return;
    }

    await sendOperatorMessage(text);
    await pollOnce();
  }

  els.chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.chatForm.requestSubmit();
    }
  });

  els.chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = els.chatInput.value;
    els.chatInput.value = "";

    try {
      await handleSubmitMessage(text);
    } catch (error) {
      showAlert(`发送失败: ${error.message}`);
    }
  });

  els.restartBtn.addEventListener("click", () => {
    resetState();
    appendMessage({
      role: "system",
      text: "已重置会话。发送第一条消息可启动新任务。",
      time: new Date().toISOString(),
    });
  });

  els.reportBtn.addEventListener("click", async () => {
    if (!state.runId) {
      showAlert("当前没有可导出的运行");
      return;
    }

    try {
      const report = await request(`/api/runs/${state.runId}/report`);
      els.reportBox.textContent = toText(report.report_markdown);
      showAlert("报告已刷新到左侧面板");
    } catch (error) {
      showAlert(`报告导出失败: ${error.message}`);
    }
  });

  async function submitHumanReview(decision) {
    if (!state.runId) {
      showAlert("当前没有运行");
      return;
    }
    if (!state.currentWorkItemId) {
      showAlert("当前未选择 WorkItem");
      return;
    }
    await request(`/api/runs/${state.runId}/human-review`, {
      method: "POST",
      body: JSON.stringify({
        work_item_id: state.currentWorkItemId,
        decision,
        note: toText(els.humanReviewNote && els.humanReviewNote.value),
      }),
    });
    if (els.humanReviewNote) {
      els.humanReviewNote.value = "";
    }
    await pollOnce();
  }

  async function pauseRun() {
    if (!state.runId) {
      showAlert("当前没有运行");
      return;
    }
    await request(`/api/runs/${state.runId}/pause`, {
      method: "POST",
      body: JSON.stringify({
        reason: "human_request",
        note: toText(els.humanReviewNote && els.humanReviewNote.value),
      }),
    });
    await pollOnce();
  }

  async function resumeRun() {
    if (!state.runId) {
      showAlert("当前没有运行");
      return;
    }
    await request(`/api/runs/${state.runId}/resume`, { method: "POST", body: "{}" });
    await pollOnce();
  }

  if (els.approveBtn) {
    els.approveBtn.addEventListener("click", () => {
      submitHumanReview("approve").catch((error) => showAlert(`提交失败: ${error.message}`));
    });
  }

  if (els.rejectBtn) {
    els.rejectBtn.addEventListener("click", () => {
      submitHumanReview("reject").catch((error) => showAlert(`提交失败: ${error.message}`));
    });
  }

  if (els.pauseBtn) {
    els.pauseBtn.addEventListener("click", () => {
      pauseRun().catch((error) => showAlert(`暂停失败: ${error.message}`));
    });
  }

  if (els.resumeBtn) {
    els.resumeBtn.addEventListener("click", () => {
      resumeRun().catch((error) => showAlert(`继续失败: ${error.message}`));
    });
  }

  resetState();
  appendMessage({
    role: "system",
    text: "欢迎使用会话机器人。发送第一条消息开始执行任务。",
    time: new Date().toISOString(),
  });
})();
