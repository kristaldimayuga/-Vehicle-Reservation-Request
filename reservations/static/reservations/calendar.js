/* GovFleet — F-01 Vehicle Reservation Request page.
 * Talks to Django only through the JSON API; never touches the database.
 * All server text is inserted with textContent to avoid XSS. */
(function () {
  "use strict";

  const app = document.getElementById("app");
  const urls = {
    vehicles: app.dataset.vehiclesUrl,
    events: app.dataset.eventsUrl,
    reservations: app.dataset.reservationsUrl,
    availability: (id) => app.dataset.availabilityUrlTemplate.replace("/0/", `/${encodeURIComponent(id)}/`),
    login: app.dataset.loginUrl,
  };
  // Server booking horizon (VehicleReservationService.MAX_ADVANCE).
  const maxAdvanceMs = Number(app.dataset.maxAdvanceSeconds) * 1000;

  const MESSAGES = {
    unavailable: "GovFleet is temporarily unavailable. Please try again in a moment.",
    network: "Network error. Please check your connection and try again.",
    throttled: "You have sent too many reservation requests. Please wait a while before trying again.",
  };

  // Error whose message is safe and meant to be shown to the user.
  class UserFacingError extends Error {}
  class NotAuthenticatedError extends Error {}

  const form = document.getElementById("reservation-form");
  const vehicleSelect = document.getElementById("vehicle");
  const vehicleFilter = document.getElementById("vehicle-filter");
  const startInput = document.getElementById("start_time");
  const endInput = document.getElementById("end_time");
  const purposeInput = document.getElementById("purpose");
  const checkButton = document.getElementById("check-availability");
  const submitButton = form.querySelector("button[type=submit]");
  const result = document.getElementById("result");

  // --- helpers --------------------------------------------------------------

  function getCookie(name) {
    const match = document.cookie.split("; ").find((row) => row.startsWith(name + "="));
    return match ? decodeURIComponent(match.split("=")[1]) : "";
  }

  async function api(url, options = {}) {
    let response;
    try {
      response = await fetch(url, {
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        ...options,
      });
    } catch (_) {
      throw new UserFacingError(MESSAGES.network);
    }
    if (response.status === 401) {
      window.location.href = `${urls.login}?next=${encodeURIComponent(window.location.pathname)}`;
      throw new NotAuthenticatedError("Not authenticated");
    }
    if (response.status === 503) {
      throw new UserFacingError(MESSAGES.unavailable);
    }
    let body = null;
    try { body = await response.json(); } catch (_) { /* empty body */ }
    return { status: response.status, body };
  }

  // Show a failed request's error (nothing for a login redirect).
  function showRequestError(err) {
    if (err instanceof NotAuthenticatedError) return;
    showResult("error", err instanceof UserFacingError ? err.message : "Something went wrong. Please try again later.");
  }

  // datetime-local value ("2026-11-25T08:00") -> ISO string with timezone.
  function localToIso(value) {
    return value ? new Date(value).toISOString() : "";
  }

  // Date -> datetime-local value in the browser's local time.
  function dateToLocalInput(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
      `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function formatRange(start, end) {
    const opts = { dateStyle: "medium", timeStyle: "short" };
    return `${new Date(start).toLocaleString(undefined, opts)} – ${new Date(end).toLocaleString(undefined, opts)}`;
  }

  function clearErrors() {
    form.querySelectorAll(".field-error").forEach((el) => { el.textContent = ""; });
    result.hidden = true;
    result.replaceChildren();
  }

  function showResult(kind, heading, items = []) {
    result.className = `alert ${kind}`;
    const strong = document.createElement("strong");
    strong.textContent = heading;
    result.replaceChildren(strong);
    if (items.length) {
      const ul = document.createElement("ul");
      items.forEach((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        ul.appendChild(li);
      });
      result.appendChild(ul);
    }
    result.hidden = false;
  }

  function showFieldErrors(errors) {
    const general = [];
    Object.entries(errors || {}).forEach(([field, messages]) => {
      const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
      const slot = form.querySelector(`[data-error-for="${CSS.escape(field)}"]`);
      if (slot) slot.textContent = text;
      else general.push(text);
    });
    showResult("error", "Please correct the highlighted fields.", general);
  }

  function showConflicts(body) {
    const items = (body.conflicts || []).map(
      (c) => `Booked ${formatRange(c.start_time, c.end_time)} (${c.status.toLowerCase()})`
    );
    showResult("error", body.detail || "Vehicle is already reserved for that time.", items);
  }

  function clientValidate() {
    const errors = {};
    if (!vehicleSelect.value) errors.vehicle = ["Select a vehicle."];
    if (!startInput.value) errors.start_time = ["Start time is required."];
    if (!endInput.value) errors.end_time = ["End time is required."];
    if (startInput.value && endInput.value && new Date(endInput.value) <= new Date(startInput.value)) {
      errors.end_time = ["End time must be after start time."];
    }
    return errors;
  }

  function setBusy(busy) {
    checkButton.disabled = busy;
    submitButton.disabled = busy;
  }

  // --- vehicles -------------------------------------------------------------

  async function loadVehicles() {
    let status, body;
    try {
      ({ status, body } = await api(urls.vehicles));
    } catch (err) {
      showRequestError(err);
      return;
    }
    if (status !== 200 || !Array.isArray(body)) {
      showResult("error", "Could not load vehicles. Please refresh the page.");
      return;
    }
    if (!body.length) {
      showResult("error", "No vehicles are available for reservation yet.");
    }
    body.forEach((v) => {
      const label = `${v.plate_number} — ${v.name}${v.capacity ? ` (${v.capacity} seats)` : ""}`;
      vehicleSelect.add(new Option(label, v.id));
      vehicleFilter.add(new Option(label, v.id));
    });
  }

  // --- calendar -------------------------------------------------------------

  const calendar = new FullCalendar.Calendar(document.getElementById("calendar"), {
    initialView: "timeGridWeek",
    headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,timeGridDay" },
    nowIndicator: true,
    selectable: true,
    selectMirror: true,
    selectOverlap: true,
    allDaySlot: false,
    height: "auto",
    // Mirrors the server rule exactly: a booking may start at most
    // MAX_ADVANCE from now. The limit comes from the server (data attribute).
    validRange: () => {
      const today = new Date(new Date().setHours(0, 0, 0, 0));
      return { start: today, end: new Date(Date.now() + maxAdvanceMs) };
    },
    events: async (info, success, failure) => {
      const params = new URLSearchParams({ start: info.start.toISOString(), end: info.end.toISOString() });
      if (vehicleFilter.value) params.set("vehicle", vehicleFilter.value);
      try {
        const { status, body } = await api(`${urls.events}?${params}`);
        if (status === 200 && Array.isArray(body)) success(body);
        else failure(new Error("Failed to load reservations"));
      } catch (err) {
        failure(err);
      }
    },
    eventSourceFailure: (err) => {
      if (err instanceof UserFacingError) showRequestError(err);
      else if (!(err instanceof NotAuthenticatedError)) showResult("error", "Could not load reservations for this period.");
    },
    select: (info) => {
      clearErrors();
      startInput.value = dateToLocalInput(info.start);
      endInput.value = dateToLocalInput(info.end);
      if (vehicleFilter.value) vehicleSelect.value = vehicleFilter.value;
      (vehicleSelect.value ? purposeInput : vehicleSelect).focus();
    },
    eventClick: (info) => {
      const p = info.event.extendedProps;
      const items = [formatRange(info.event.start, info.event.end), `Status: ${p.status.toLowerCase()}`];
      if (p.isOwn && p.purpose) items.push(`Purpose: ${p.purpose}`);
      showResult(p.isOwn ? "ok" : "error", info.event.title, items);
    },
  });

  vehicleFilter.addEventListener("change", () => calendar.refetchEvents());

  // --- actions --------------------------------------------------------------

  checkButton.addEventListener("click", async () => {
    clearErrors();
    const errors = clientValidate();
    delete errors.purpose;
    if (Object.keys(errors).length) return showFieldErrors(errors);

    setBusy(true);
    try {
      const params = new URLSearchParams({
        start_time: localToIso(startInput.value),
        end_time: localToIso(endInput.value),
      });
      const { status, body } = await api(`${urls.availability(vehicleSelect.value)}?${params}`);
      if (status === 200 && body.available) {
        showResult("ok", "Vehicle is available for this time slot.");
      } else if (status === 200) {
        showConflicts({ detail: "Vehicle is not available for this time slot.", conflicts: body.conflicts });
      } else if (status === 400) {
        showFieldErrors(body);
      } else {
        showResult("error", (body && body.detail) || "Could not check availability.");
      }
    } catch (err) {
      showRequestError(err);
    } finally {
      setBusy(false);
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearErrors();
    const errors = clientValidate();
    if (!purposeInput.value.trim()) errors.purpose = ["Purpose is required."];
    if (Object.keys(errors).length) return showFieldErrors(errors);

    setBusy(true);
    try {
      const { status, body } = await api(urls.reservations, {
        method: "POST",
        body: JSON.stringify({
          vehicle: Number(vehicleSelect.value),
          start_time: localToIso(startInput.value),
          end_time: localToIso(endInput.value),
          purpose: purposeInput.value.trim(),
        }),
      });
      if (status === 201) {
        showResult("ok", `Request #${body.id} submitted — status: ${body.status.toLowerCase()}.`, [
          `${body.vehicle.plate_number} — ${body.vehicle.name}`,
          formatRange(body.start_time, body.end_time),
          "A scheduler will review your request.",
        ]);
        form.reset();
        calendar.unselect();
        calendar.refetchEvents();
      } else if (status === 409) {
        showConflicts(body);
        calendar.refetchEvents();
      } else if (status === 400) {
        showFieldErrors(body);
      } else if (status === 403) {
        showResult("error", "You do not have permission to make reservations.");
      } else if (status === 429) {
        showResult("error", MESSAGES.throttled);
      } else {
        showResult("error", "Something went wrong. Please try again later.");
      }
    } catch (err) {
      showRequestError(err);
    } finally {
      setBusy(false);
    }
  });

  loadVehicles().finally(() => calendar.render());
})();
