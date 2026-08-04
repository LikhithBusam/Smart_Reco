/**
 * SmartReco behavioral event tracker.
 * In-memory queue only (never localStorage). Flushes on: queue >= 20 events,
 * 10s elapsed, or the tab hiding/unloading (via sendBeacon so it survives
 * navigation). Only semantic events are sent — raw mousemove/scroll are never
 * tracked; time-on-page is aggregated client-side into fixed intervals.
 * See docs/ARCHITECTURE.md §4.
 */
(function () {
  "use strict";

  const ENDPOINT = "/api/events/batch";
  const FLUSH_MAX_QUEUE = 20;
  const FLUSH_INTERVAL_MS = 10000;
  const TIME_ON_PAGE_INTERVAL_MS = 15000;
  const SESSION_KEY = "smartreco_session_id";

  let queue = [];
  let flushTimer = null;

  function getSessionId() {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id =
        window.crypto && crypto.randomUUID
          ? crypto.randomUUID()
          : Date.now() + "-" + Math.random().toString(16).slice(2);
      sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  }

  function enqueue(eventType, entityType, entityId, metadata) {
    queue.push({
      event_type: eventType,
      entity_type: entityType || null,
      entity_id: entityId || null,
      metadata: metadata || null,
      session_id: getSessionId(),
    });

    if (queue.length >= FLUSH_MAX_QUEUE) {
      flush(false);
    } else {
      scheduleFlush();
    }
  }

  function scheduleFlush() {
    if (flushTimer) return;
    flushTimer = setTimeout(function () {
      flush(false);
    }, FLUSH_INTERVAL_MS);
  }

  function flush(useBeacon) {
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    if (queue.length === 0) return;

    const payload = JSON.stringify({ events: queue });
    queue = [];

    if (useBeacon && navigator.sendBeacon) {
      const blob = new Blob([payload], { type: "application/json" });
      navigator.sendBeacon(ENDPOINT, blob);
      return;
    }

    // Fire-and-forget by design — tracking must never block or break the page.
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      keepalive: true,
      credentials: "same-origin",
    }).catch(function () {});
  }

  // Aggregate dwell time client-side; emit one event per interval, not per tick.
  let timeOnPageAccumulatedMs = 0;
  let lastTick = Date.now();

  setInterval(function () {
    const now = Date.now();
    if (document.visibilityState === "visible") {
      timeOnPageAccumulatedMs += now - lastTick;
    }
    lastTick = now;

    if (timeOnPageAccumulatedMs >= TIME_ON_PAGE_INTERVAL_MS) {
      enqueue("time_on_page", "page", null, {
        path: location.pathname,
        seconds: Math.round(timeOnPageAccumulatedMs / 1000),
      });
      timeOnPageAccumulatedMs = 0;
    }
  }, TIME_ON_PAGE_INTERVAL_MS);

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") flush(true);
  });
  window.addEventListener("pagehide", function () {
    flush(true);
  });

  window.SmartRecoTracker = {
    trackView: function (entityType, entityId, metadata) {
      enqueue("view", entityType, entityId, metadata);
    },
    trackSearch: function (query) {
      enqueue("search", null, null, { query: query });
    },
    trackClick: function (entityType, entityId, metadata) {
      enqueue("click", entityType, entityId, metadata);
    },
  };
})();
