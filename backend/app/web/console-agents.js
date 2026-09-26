(() => {
  const MAX_VISIBLE_TASKS = 10;
  const busyTasks = new Set();
  let root = null;
  let agents = [];
  let tasks = [];
  let loading = false;

  const makeNode = (tag, className, content) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  };

  function mount() {
    if (root) return;
    const grid = document.querySelector("#portal-panel-intelligence .owner-portal-grid");
    if (!grid) return;

    root = document.createElement("section");
    root.id = "agent-task-console";
    root.className = "panel agent-task-console";
    root.setAttribute("aria-labelledby", "agent-task-console-title");
    root.innerHTML = [
      '<div class="section-head agent-task-heading">',
      '<div><p class="eyebrow">SELDRUNE AGENT FABRIC</p>',
      '<h2 id="agent-task-console-title">Assign work to a Seldrune agent</h2>',
      '<p>Run tasks through the registered agent runtime and inspect each recorded result.</p></div>',
      '<button id="agent-task-refresh" type="button" class="ghost">Refresh agents</button></div>',
      '<div class="agent-task-metrics" aria-label="Agent task status">',
      '<article><small>Active agents</small><strong id="agent-task-active-count">—</strong></article>',
      '<article><small>Queued</small><strong id="agent-task-queued-count">—</strong></article>',
      '<article><small>Assigned</small><strong id="agent-task-assigned-count">—</strong></article>',
      '<article><small>Running</small><strong id="agent-task-running-count">—</strong></article>',
      '<article><small>Failed</small><strong id="agent-task-failed-count">—</strong></article></div>',
      '<form id="agent-task-form" class="agent-task-form">',
      '<label>Task title<input id="agent-task-title" type="text" maxlength="200" required></label>',
      '<label>Objective<textarea id="agent-task-objective" maxlength="12000" rows="3" required></textarea></label>',
      '<div class="agent-task-form-submit"><label>Run with active agent<select id="agent-task-agent" required></select></label>',
      '<button id="agent-task-submit" type="submit" disabled>Create and run</button></div>',
      '<p id="agent-task-feedback" class="agent-task-feedback" role="status" aria-live="polite">Checking agent availability…</p>',
      '</form>',
      '<div class="section-head agent-task-list-heading"><div><p class="eyebrow">DURABLE TASK RECORDS</p><h3>Recent agent work</h3></div></div>',
      '<div id="agent-task-list" class="agent-task-list"><div class="empty">Loading agent tasks…</div></div>',
      '<p class="agent-task-footnote">Retries create a new attempt. Model use stays within the selected agent configuration and Seldrune spend limits.</p>',
    ].join("");
    grid.prepend(root);

    root.querySelector("#agent-task-refresh").addEventListener("click", () => {
      void refresh();
    });
    root.querySelector("#agent-task-form").addEventListener("submit", createAndRunTask);
    root.querySelector("#agent-task-list").addEventListener("click", event => {
      const button = event.target.closest("[data-agent-action]");
      if (!button || button.disabled) return;
      const task = tasks.find(item => item.id === button.dataset.taskId);
      if (!task) return;
      if (button.dataset.agentAction === "run") void runTask(task.id, button);
      if (button.dataset.agentAction === "assign") void assignAndRunTask(task, button);
      if (button.dataset.agentAction === "retry") void retryTask(task, button);
    });
  }

  function activeAgents() {
    return agents.filter(agent => agent.status === "active");
  }

  function setFeedback(message, kind) {
    const feedback = root?.querySelector("#agent-task-feedback");
    if (!feedback) return;
    feedback.textContent = message;
    feedback.dataset.state = kind || "info";
  }

  function refreshAgentSelect() {
    const select = root?.querySelector("#agent-task-agent");
    const submit = root?.querySelector("#agent-task-submit");
    if (!select || !submit) return;
    const selected = select.value;
    select.replaceChildren();
    const option = makeNode(
      "option",
      "",
      activeAgents().length ? "Choose an active Seldrune agent" : "No active agent configured",
    );
    option.value = "";
    select.append(option);
    activeAgents().forEach(agent => {
      const item = makeNode("option", "", agent.name + " · " + agent.capabilities.join(", "));
      item.value = agent.id;
      select.append(item);
    });
    if (activeAgents().some(agent => agent.id === selected)) select.value = selected;
    submit.disabled = activeAgents().length === 0;
  }

  function countStatuses() {
    const counts = {queued: 0, assigned: 0, running: 0, failed: 0};
    tasks.forEach(task => {
      if (Object.prototype.hasOwnProperty.call(counts, task.status)) counts[task.status] += 1;
    });
    root.querySelector("#agent-task-active-count").textContent = String(activeAgents().length);
    root.querySelector("#agent-task-queued-count").textContent = String(counts.queued);
    root.querySelector("#agent-task-assigned-count").textContent = String(counts.assigned);
    root.querySelector("#agent-task-running-count").textContent = String(counts.running);
    root.querySelector("#agent-task-failed-count").textContent = String(counts.failed);
  }

  function agentName(agentId) {
    const agent = agents.find(item => item.id === agentId);
    return agent ? agent.name + (agent.status === "active" ? "" : " · " + agent.status) : "No agent assigned";
  }

  function formatTime(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
  }

  function actionButton(label, action, task, disabled) {
    const button = makeNode("button", action === "retry" ? "ghost" : "", label);
    button.type = "button";
    button.dataset.agentAction = action;
    button.dataset.taskId = task.id;
    button.disabled = Boolean(disabled);
    return button;
  }

  function renderTasks() {
    const list = root?.querySelector("#agent-task-list");
    if (!list) return;
    list.replaceChildren();
    if (!tasks.length) {
      list.append(makeNode("div", "empty", "No tasks yet. Create one above to run it through a Seldrune agent."));
      return;
    }

    tasks.slice(0, MAX_VISIBLE_TASKS).forEach(task => {
      const card = makeNode("article", "agent-task-card");
      const header = makeNode("div", "agent-task-card-header");
      const title = makeNode("h4", "", task.title || "Untitled task");
      const statusSlug = String(task.status || "unknown").replace(/[^a-z0-9-]/gi, "");
      const status = makeNode("span", "agent-task-status state-" + statusSlug, String(task.status || "unknown").replaceAll("_", " "));
      header.append(title, status);

      const objective = makeNode("p", "agent-task-objective", task.objective || "");
      const meta = makeNode(
        "p",
        "agent-task-meta",
        agentName(task.assigned_agent_id) + (formatTime(task.created_at) ? " · " + formatTime(task.created_at) : ""),
      );
      card.append(header, objective, meta);

      const outputText = task.output_data && task.output_data.text;
      if (typeof outputText === "string" && outputText.trim()) {
        card.append(makeNode("p", "agent-task-output", outputText));
      }
      if (task.error_message) {
        card.append(makeNode("p", "agent-task-error", task.error_message));
      }

      const actions = makeNode("div", "agent-task-actions");
      const agent = agents.find(item => item.id === task.assigned_agent_id);
      const isBusy = busyTasks.has(task.id);
      if (task.status === "assigned" && agent && agent.status === "active") {
        actions.append(actionButton(isBusy ? "Running…" : "Run with agent", "run", task, isBusy));
      } else if (task.status === "queued" && activeAgents().length) {
        actions.append(actionButton("Assign selected agent and run", "assign", task, isBusy));
      } else if (task.status === "failed" && agent && agent.status === "active") {
        actions.append(actionButton("Retry as new attempt", "retry", task, isBusy));
      }
      if (actions.childElementCount) card.append(actions);
      list.append(card);
    });
  }

  function render() {
    if (!root) return;
    countStatuses();
    refreshAgentSelect();
    renderTasks();
  }

  function upsertTask(task) {
    tasks = [task, ...tasks.filter(item => item.id !== task.id)];
    render();
  }

  async function refresh() {
    if (!root || loading || typeof state === "undefined" || !state.org || typeof api !== "function") return;
    loading = true;
    const refreshButton = root.querySelector("#agent-task-refresh");
    if (refreshButton) refreshButton.disabled = true;
    try {
      const result = await Promise.all([api("/agents"), api("/tasks")]);
      agents = Array.isArray(result[0]) ? result[0] : [];
      tasks = Array.isArray(result[1]) ? result[1] : [];
      render();
      setFeedback(
        activeAgents().length
          ? "Seldrune agent runtime ready · select an agent or run an assigned task."
          : "No active agent is configured for this organization.",
        activeAgents().length ? "ready" : "attention",
      );
    } catch (error) {
      setFeedback("Agent status could not be loaded: " + error.message, "error");
    } finally {
      loading = false;
      if (refreshButton) refreshButton.disabled = false;
    }
  }

  async function runTask(taskId, button) {
    if (busyTasks.has(taskId) || typeof api !== "function") return;
    busyTasks.add(taskId);
    if (button) button.disabled = true;
    setFeedback("Seldrune is running the assigned agent and recording its result…", "running");
    try {
      const completed = await api("/tasks/" + encodeURIComponent(taskId) + "/execute", {
        method: "POST",
      });
      upsertTask(completed);
      setFeedback(
        completed.status === "succeeded"
          ? "Agent task completed and recorded."
          : "Agent task returned status: " + completed.status + ".",
        completed.status === "succeeded" ? "ready" : "attention",
      );
    } catch (error) {
      setFeedback("Agent task did not complete: " + error.message, "error");
    } finally {
      busyTasks.delete(taskId);
      await refresh();
    }
  }

  async function assignAndRunTask(task, button) {
    const select = root.querySelector("#agent-task-agent");
    if (!select.value) {
      setFeedback("Choose an active agent before assigning this task.", "attention");
      return;
    }
    if (button) button.disabled = true;
    try {
      const assigned = await api("/tasks/" + encodeURIComponent(task.id) + "/assign", {
        method: "POST",
        body: JSON.stringify({agent_id: select.value}),
      });
      upsertTask(assigned);
      await runTask(assigned.id, button);
    } catch (error) {
      setFeedback("Task assignment failed: " + error.message, "error");
      if (button) button.disabled = false;
      await refresh();
    }
  }

  async function retryTask(task, button) {
    if (!task.assigned_agent_id) return;
    if (button) button.disabled = true;
    setFeedback("Creating a separately recorded retry attempt…", "running");
    try {
      const inputData = Object.assign({}, task.input_data || {}, {
        retry_of_task_id: task.id,
      });
      const retry = await api("/tasks", {
        method: "POST",
        body: JSON.stringify({
          title: ("Retry: " + (task.title || "Agent task")).slice(0, 200),
          objective: task.objective,
          priority: task.priority,
          input_data: inputData,
          assigned_agent_id: task.assigned_agent_id,
        }),
      });
      upsertTask(retry);
      await runTask(retry.id, button);
    } catch (error) {
      setFeedback("Retry attempt could not start: " + error.message, "error");
      if (button) button.disabled = false;
      await refresh();
    }
  }

  async function createAndRunTask(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const titleField = root.querySelector("#agent-task-title");
    const objectiveField = root.querySelector("#agent-task-objective");
    const agentField = root.querySelector("#agent-task-agent");
    const submit = root.querySelector("#agent-task-submit");
    const agentId = agentField.value;
    if (!agentId) {
      setFeedback("Choose an active agent before creating a task.", "attention");
      return;
    }
    if (submit) submit.disabled = true;
    setFeedback("Assigning the task to Seldrune's agent runtime…", "running");
    try {
      const task = await api("/tasks", {
        method: "POST",
        body: JSON.stringify({
          title: titleField.value.trim(),
          objective: objectiveField.value.trim(),
          priority: 10,
          input_data: {source: "owner-agent-workspace"},
          assigned_agent_id: agentId,
        }),
      });
      upsertTask(task);
      titleField.value = "";
      objectiveField.value = "";
      await runTask(task.id, null);
    } catch (error) {
      setFeedback("Task could not be created: " + error.message, "error");
    } finally {
      if (submit) submit.disabled = activeAgents().length === 0;
      if (form.isConnected) titleField.focus();
    }
  }

  document.addEventListener("seldrune:portal-ready", mount);
  document.addEventListener("seldrune:console-ready", () => {
    mount();
    void refresh();
  });
  document.addEventListener("seldrune:refresh", () => {
    void refresh();
  });
  document.addEventListener("seldrune:workspace-change", event => {
    if (event.detail && event.detail.workspace === "intelligence") void refresh();
  });

  if (document.querySelector("#portal-panel-intelligence")) mount();
})();