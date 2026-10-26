import { useEffect, useState } from "react";

// Responses arrive whole (no streaming), so we show staged progress instead of a frozen screen.
function describe(s) {
  switch (s.kind) {
    case "start":
      return "EdNova is reading your message…";
    case "stage":
      return s.label + "…";
    case "queued":
      return s.label || "Waiting for a free slot…";
    case "calling":
      return s.model_class === "midsize"
        ? "Asking the larger model (this can take several seconds)…"
        : "Asking the fast model…";
    case "midsize_busy":
      return "Large model busy, switching to lighter mode…";
    case "quota_wait":
      return `Quota reached, retrying in ${Math.ceil(s.seconds)} s…`;
    case "retrying":
      return s.seconds ? `Retrying in ${Math.ceil(s.seconds)} s…` : "Retrying…";
    default:
      return "Working…";
  }
}

export default function AiStatus({ status }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!status) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [status]);
  if (!status) return null;
  const secs = Math.max(0, (now - status.since) / 1000);

  return (
    <div className="ai-status" role="status" aria-live="polite">
      <span className="dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span className="ai-status-text">{describe(status)}</span>
      <span className="ai-status-time">{secs.toFixed(1)} s</span>
    </div>
  );
}
