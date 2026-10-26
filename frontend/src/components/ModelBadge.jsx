const LABELS = {
  compact: "fast model",
  midsize: "large model",
  cache: "from cache",
  rule: "instant",
};

// Shows which model answered and why: the orchestration, visible to learners and judges.
export default function ModelBadge({ msg }) {
  const cls = msg.cached ? "cache" : msg.model_class;
  return (
    <div className="badges">
      <span className={`badge badge-${cls}`} title={msg.route_reason}>
        {LABELS[cls] || cls}
        {msg.latency_ms && !msg.cached ? ` · ${(msg.latency_ms / 1000).toFixed(1)} s` : ""}
      </span>
      {msg.fell_back && <span className="badge badge-warn">lighter mode</span>}
      <span className="why">{msg.route_reason}</span>
    </div>
  );
}
