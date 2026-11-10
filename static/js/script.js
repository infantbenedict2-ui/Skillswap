const searchInput = document.querySelector("#skill-search");
const skillCards = Array.from(document.querySelectorAll(".skill-card"));
const noResults = document.querySelector("#no-results");
const currentYear = document.querySelector("#current-year");
const localToday = new Date();
const todayValue = `${localToday.getFullYear()}-${String(localToday.getMonth() + 1).padStart(2, "0")}-${String(localToday.getDate()).padStart(2, "0")}`;
document.querySelectorAll('input[type="date"]').forEach((input) => {
    input.min = todayValue;
});

document.querySelectorAll(".menu-toggle").forEach((menuButton) => {
    const navigation = document.getElementById(menuButton.getAttribute("aria-controls"));
    if (!navigation) return;

    menuButton.addEventListener("click", () => {
        const isExpanded = menuButton.getAttribute("aria-expanded") === "true";
        menuButton.setAttribute("aria-expanded", String(!isExpanded));
        menuButton.setAttribute("aria-label", isExpanded ? "Open navigation" : "Close navigation");
        navigation.classList.toggle("is-open", !isExpanded);
    });

    navigation.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => {
            menuButton.setAttribute("aria-expanded", "false");
            menuButton.setAttribute("aria-label", "Open navigation");
            navigation.classList.remove("is-open");
        });
    });
});

if (searchInput && noResults) {
    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim().toLowerCase();
        let visibleSkills = 0;

        skillCards.forEach((card) => {
            const matches = card.dataset.skill.toLowerCase().includes(query);
            card.hidden = !matches;
            visibleSkills += Number(matches);
        });

        noResults.hidden = visibleSkills > 0;
    });
}

if (currentYear) {
    currentYear.textContent = String(new Date().getFullYear());
}

document.querySelectorAll("[data-avatar-image]").forEach((image) => {
    const showFallback = () => image.remove();

    if (image.complete && image.naturalWidth === 0) {
        showFallback();
    } else {
        image.addEventListener("error", showFallback, { once: true });
    }
});

const feedback = (container, message, isError = false) => {
    const target = container?.querySelector("[data-feedback]") || document.querySelector("[data-feedback]");
    if (!target) return;
    target.textContent = message;
    target.classList.toggle("is-error", isError);
    target.classList.toggle("is-visible", Boolean(message));
};

const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {
        credentials: "same-origin",
        headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
        ...options,
    });
    if (response.status === 204) return {};
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status}).`);
    return payload;
};

const makeElement = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
};

const formDataObject = (form) => Object.fromEntries(new FormData(form).entries());

const submitApiForm = async (form, payload) => {
    const button = form.querySelector('button[type="submit"]');
    if (button?.disabled) return;
    if (button) button.disabled = true;
    try {
        await fetchJson(form.dataset.endpoint, {
            method: form.dataset.method || "POST",
            body: JSON.stringify(payload),
        });
        return true;
    } finally {
        if (button) button.disabled = false;
    }
};

const sessionRoot = document.querySelector("[data-session-center]");
if (sessionRoot) {
    const sessionList = sessionRoot.querySelector("[data-session-list]");
    const sessionFilter = sessionRoot.querySelector("[data-session-filter]");
    const sessionFeedback = sessionRoot.querySelector("[data-session-feedback]");
    const sessionEndpoint = sessionRoot.dataset.listEndpoint;
    const currentUserId = Number(sessionRoot.dataset.currentUserId);

    const loadSessions = async () => {
        sessionList.replaceChildren(makeElement("p", "app-loading", "Loading your sessions…"));
        try {
            const result = await fetchJson(`${sessionEndpoint}?filter=${encodeURIComponent(sessionFilter.value)}`);
            sessionList.replaceChildren();
            if (!result.sessions.length) {
                sessionList.append(makeElement("p", "app-empty", "No sessions in this view yet."));
                return;
            }
            result.sessions.forEach((session) => {
                const card = makeElement("article", "session-card");
                const heading = makeElement("div", "session-card-heading");
                const title = makeElement("div");
                title.append(makeElement("p", "eyebrow", session.skill.name));
                title.append(makeElement("h3", "", session.title));
                heading.append(title, makeElement("span", `session-status status-${session.status.toLowerCase()}`, session.status.replaceAll("_", " ")));
                card.append(heading);
                card.append(makeElement("p", "session-participants", `Teacher: ${session.teacher.name} · Learner: ${session.learner.name}`));
                card.append(makeElement("p", "session-date", `${session.date} · ${session.start_time.slice(0, 5)}–${session.end_time.slice(0, 5)}`));
                if (session.notes) card.append(makeElement("p", "session-notes", session.notes));
                if (session.status === "SCHEDULED") {
                    const edit = makeElement("details", "session-edit");
                    edit.append(makeElement("summary", "", "Edit date, time or notes"));
                    const editForm = makeElement("form", "session-edit-form");
                    editForm.dataset.sessionEdit = session.id;
                    [["date", "date", session.date], ["start_time", "time", session.start_time.slice(0, 5)], ["end_time", "time", session.end_time.slice(0, 5)]].forEach(([name, type, value]) => {
                        const label = makeElement("label");
                        label.append(makeElement("span", "", name.replace("_", " ")));
                        const input = makeElement("input");
                        input.name = name;
                        input.type = type;
                        input.value = value;
                        if (type === "date") input.min = todayValue;
                        input.required = true;
                        label.append(input);
                        editForm.append(label);
                    });
                    const notesLabel = makeElement("label");
                    notesLabel.append(makeElement("span", "", "Notes"));
                    const notesInput = makeElement("textarea");
                    notesInput.name = "notes";
                    notesInput.maxLength = 4000;
                    notesInput.value = session.notes || "";
                    notesLabel.append(notesInput);
                    editForm.append(notesLabel);
                    const save = makeElement("button", "button button-outline", "Save changes");
                    save.type = "submit";
                    editForm.append(save);
                    edit.append(editForm);
                    card.append(edit);
                }
                const actions = makeElement("div", "session-actions");
                if (session.status === "SCHEDULED") {
                    actions.append(sessionAction(session.id, "start", "Start session", "button button-dark"));
                    actions.append(sessionAction(session.id, "cancel", "Cancel", "button button-outline"));
                } else if (session.status === "IN_PROGRESS") {
                    const hasConfirmed = session.teacher.id === currentUserId ? session.teacher_confirmed : session.learner_confirmed;
                    if (!hasConfirmed) {
                        actions.append(sessionAction(session.id, "confirm-completion", "Confirm completion", "button button-dark"));
                    } else {
                        actions.append(makeElement("span", "session-waiting", "Waiting for the other participant to confirm."));
                    }
                    actions.append(sessionAction(session.id, "cancel", "Cancel", "button button-outline"));
                } else if (session.status === "COMPLETED" && !(session.teacher_confirmed && session.learner_confirmed)) {
                    actions.append(sessionAction(session.id, "confirm-completion", "Confirm completion", "button button-dark"));
                }
                if (actions.childElementCount) card.append(actions);
                if (["COMPLETED", "IN_PROGRESS"].includes(session.status) && session.teacher_confirmed !== undefined) {
                    card.append(makeElement("p", "session-confirmation", `Completion confirmations: teacher ${session.teacher_confirmed ? "yes" : "pending"} · learner ${session.learner_confirmed ? "yes" : "pending"}`));
                }
                sessionList.append(card);
            });
        } catch (error) {
            sessionList.replaceChildren(makeElement("p", "app-empty is-error", error.message));
        }
    };

    function sessionAction(sessionId, action, label, className) {
        const button = makeElement("button", className, label);
        button.type = "button";
        button.dataset.sessionAction = action;
        button.dataset.sessionId = sessionId;
        return button;
    }

    sessionFilter.addEventListener("change", loadSessions);
    sessionList.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-session-action]");
        if (!button) return;
        button.disabled = true;
        try {
            await fetchJson(`/api/sessions/${button.dataset.sessionId}/${button.dataset.sessionAction}`, { method: "POST", body: "{}" });
            feedback(sessionRoot, "Session updated.");
            await loadSessions();
        } catch (error) {
            feedback(sessionRoot, error.message, true);
            button.disabled = false;
        }
    });
    sessionList.addEventListener("submit", async (event) => {
        const form = event.target.closest("[data-session-edit]");
        if (!form) return;
        event.preventDefault();
        const values = formDataObject(form);
        try {
            await fetchJson(`/api/sessions/${form.dataset.sessionEdit}`, { method: "PUT", body: JSON.stringify(values) });
            feedback(sessionRoot, "Session details saved.");
            await loadSessions();
        } catch (error) {
            feedback(sessionRoot, error.message, true);
        }
    });
    sessionRoot.querySelector(".session-create-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const values = formDataObject(form);
        const requestOption = form.querySelector("#session-request").selectedOptions[0];
        if (!requestOption?.dataset.teacher) {
            feedback(sessionRoot, "Choose an accepted swap request.", true);
            return;
        }
        if (values.end_time <= values.start_time) {
            feedback(sessionRoot, "End time must be later than start time.", true);
            return;
        }
        values.skill_request_id = Number(values.skill_request_id);
        values.teacher_id = Number(requestOption.dataset.teacher);
        values.learner_id = Number(requestOption.dataset.learner);
        try {
            await submitApiForm(form, values);
            form.reset();
            feedback(sessionRoot, "Session scheduled and your partner has been notified.");
            sessionFilter.value = "upcoming";
            await loadSessions();
        } catch (error) {
            feedback(sessionRoot, error.message, true);
        }
    });
    loadSessions();
}

const privacyForm = document.querySelector("[data-privacy-form]");
if (privacyForm) {
    const readSettings = async () => {
        const settings = await fetchJson(privacyForm.dataset.endpoint);
        privacyForm.elements.profile_visibility.value = settings.profile_visibility;
        privacyForm.elements.location_visibility.checked = settings.location_visibility;
        privacyForm.elements.online_status_visibility.checked = settings.online_status_visibility;
        Object.entries(settings.notification_preferences).forEach(([key, enabled]) => {
            privacyForm.elements[key].checked = enabled;
        });
    };
    readSettings().catch((error) => feedback(privacyForm, error.message, true));
    privacyForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submitButton = privacyForm.querySelector('button[type="submit"]');
        if (submitButton?.disabled) return;
        if (submitButton) submitButton.disabled = true;
        const body = {
            profile_visibility: privacyForm.elements.profile_visibility.value,
            location_visibility: privacyForm.elements.location_visibility.checked,
            online_status_visibility: privacyForm.elements.online_status_visibility.checked,
            notification_preferences: {
                requests: privacyForm.elements.requests.checked,
                messages: privacyForm.elements.messages.checked,
                sessions: privacyForm.elements.sessions.checked,
                ratings: privacyForm.elements.ratings.checked,
            },
        };
        try {
            await fetchJson(privacyForm.dataset.endpoint, { method: "PUT", body: JSON.stringify(body) });
            feedback(privacyForm, "Privacy settings saved.");
        } catch (error) {
            feedback(privacyForm, error.message, true);
        } finally {
            if (submitButton) submitButton.disabled = false;
        }
    });
}

const blockedRoot = document.querySelector("[data-blocked-users]");
if (blockedRoot) {
    const list = blockedRoot.querySelector("[data-blocked-list]");
    const renderBlocked = async () => {
        list.replaceChildren(makeElement("p", "app-loading", "Loading your block list…"));
        try {
            const result = await fetchJson("/api/users/me/blocked");
            list.replaceChildren();
            if (!result.blocked_users.length) {
                list.append(makeElement("p", "app-empty", "You haven’t blocked any members."));
                return;
            }
            result.blocked_users.forEach((user) => {
                const row = makeElement("article", "blocked-row");
                const name = makeElement("div", "blocked-user-name");
                name.append(makeElement("strong", "", user.name), makeElement("span", "", `@${user.username}`));
                row.append(name, makeElement("time", "", new Date(user.blocked_at).toLocaleDateString()));
                const button = makeElement("button", "button button-outline", "Unblock");
                button.type = "button";
                button.dataset.unblockUser = user.id;
                row.append(button);
                list.append(row);
            });
        } catch (error) {
            list.replaceChildren(makeElement("p", "app-empty is-error", error.message));
        }
    };
    list.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-unblock-user]");
        if (!button) return;
        button.disabled = true;
        try {
            await fetchJson(`/api/users/${button.dataset.unblockUser}/block`, { method: "DELETE" });
            feedback(blockedRoot, "Member unblocked.");
            await renderBlocked();
        } catch (error) {
            feedback(blockedRoot, error.message, true);
            button.disabled = false;
        }
    });
    renderBlocked();
}

document.querySelectorAll("[data-report-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = formDataObject(form);
        try {
            await submitApiForm(form, {
                reported_user_id: Number(form.dataset.reportedUser),
                reason: values.reason,
                description: values.description,
            });
            form.reset();
            feedback(form, "Your report was submitted to the moderation team.");
        } catch (error) {
            feedback(form, error.message, true);
        }
    });
});

document.querySelectorAll("[data-rating-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = formDataObject(form);
        try {
            await submitApiForm(form, {
                session_id: Number(form.dataset.sessionId),
                rating: Number(values.rating),
                comment: values.comment || "",
            });
            feedback(form, "Rating submitted. Thank you for sharing feedback.");
            form.replaceChildren(makeElement("p", "submitted-review", "Your rating has been submitted."));
        } catch (error) {
            feedback(form, error.message, true);
        }
    });
});

document.querySelectorAll("[data-insert-emoji]").forEach((button) => {
    button.addEventListener("click", () => {
        const textarea = button.closest("form")?.querySelector("textarea");
        if (!textarea) return;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const emoji = button.dataset.insertEmoji;
        textarea.setRangeText(emoji, start, end, "end");
        textarea.focus();
    });
});

document.querySelectorAll("form:not([data-api-form]):not([data-privacy-form]):not([data-report-form]):not([data-rating-form])").forEach((form) => {
    form.addEventListener("submit", () => {
        const button = form.querySelector('button[type="submit"]');
        if (button) {
            button.disabled = true;
            button.setAttribute("aria-busy", "true");
        }
    });
});