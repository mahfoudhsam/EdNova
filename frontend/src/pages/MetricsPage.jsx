import { useCallback, useEffect, useState } from "react";

const fmtPct = (x) => `${Math.round((x || 0) * 100)}%`;
const fmtMs = (x) => (x == null ? "–" : `${(x / 1000).toFixed(1)} s`);

export default function MetricsPage() {
  const [data, setData] = useState(null);
  const [routing, setRouting] = useState(null);
  const [quota, setQuota] = useState(null);
  const [token, setToken] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    fetch("/api/metrics").then((r) => r.json()).then(setData).catch(() => {});
    fetch("/api/quota").then((r) => r.json()).then(setQuota).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    fetch("/api/routing").then((r) => r.json()).then(setRouting).catch(() => {});
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  const admin = async (path, body) => {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
      body: JSON.stringify(body || {}),
    });
    setNote(r.ok ? "Done." : `Refused (${r.status}). Check the admin token.`);
    load();
  };

  const s = data?.summary;
  const chaos = quota?.chaos || {};

  return (
    <main className="metrics">
      <div className="metrics-head">
        <div>
          <div className="eyebrow">Orchestration & constraints</div>
          <h1>Metrics</h1>
          <p className="muted">Mirrors the per-team metrics the organisers collect. Refreshes every 3 s.</p>
        </div>
      </div>

      {s && (
        <div className="cards">
          <div className="card accent">
            <div className="card-label">Calls on the fast model</div>
            <div className="card-value">{fmtPct(s.compact_share)}</div>
            <div className="card-sub">
              {s.calls_by_class.compact} compact · {s.calls_by_class.midsize} mid-size
            </div>
          </div>
          <div className="card">
            <div className="card-label">Cache hit rate</div>
            <div className="card-value">{fmtPct(s.cache_hit_rate)}</div>
            <div className="card-sub">{s.cache_hits} answers with 0 model calls</div>
          </div>
          <div className="card">
            <div className="card-label">Median latency</div>
            <div className="card-value">{fmtMs(s.median_latency_ms.compact)}</div>
            <div className="card-sub">mid-size {fmtMs(s.median_latency_ms.midsize)}</div>
          </div>
          <div className="card">
            <div className="card-label">Tokens in / out</div>
            <div className="card-value">
              {s.tokens_in} / {s.tokens_out}
            </div>
            <div className="card-sub">{s.embedding_calls} embedding calls</div>
          </div>
          <div className="card">
            <div className="card-label">Fallbacks & errors</div>
            <div className="card-value">{s.fallbacks}</div>
            <div className="card-sub">
              {Object.entries(s.errors_by_status).map(([k, v]) => `${k === "-1" ? "simulated" : k}: ${v}`).join(" · ") ||
                "no errors"}
            </div>
          </div>
        </div>
      )}

      <div className="metrics-grid">
        <section className="box">
          <h3>Degraded-mode switch</h3>
          <p className="muted">
            Simulates platform failures inside our gateway (works with the real API too), so you can rehearse and
            demo the fallback behaviour.
          </p>
          <div className="chaos-row">
            <span>Mid-size model saturated (503)</span>
            <button
              className={`btn small ${chaos.midsize_unavailable ? "danger" : ""}`}
              onClick={() => admin("/api/admin/chaos", { midsize_unavailable: !chaos.midsize_unavailable })}
            >
              {chaos.midsize_unavailable ? "ON · turn off" : "OFF · turn on"}
            </button>
          </div>
          <div className="chaos-row">
            <span>Quota exhausted on next call</span>
            <button className="btn small" onClick={() => admin("/api/admin/chaos", { quota_exhausted_s: 6 })}>
              Trigger 6 s wait
            </button>
          </div>
          <div className="chaos-row">
            <span>Answer cache</span>
            <button className="btn small" onClick={() => admin("/api/admin/cache/clear")}>
              Clear cache
            </button>
          </div>
          <input
            className="token"
            type="password"
            placeholder="Admin token (if ADMIN_TOKEN is set)"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
          {note && <p className="muted">{note}</p>}
          <h4>Last quota headers</h4>
          <pre className="mono">{quota ? JSON.stringify(quota.headers, null, 2) : "–"}</pre>
        </section>

        <section className="box">
          <h3>Routing table</h3>
          <table>
            <thead>
              <tr>
                <th>Step</th>
                <th>Class</th>
                <th>Max out</th>
                <th>Fallback</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {routing?.steps.map((r) => (
                <tr key={r.step}>
                  <td className="mono">{r.step}</td>
                  <td>
                    <span className={`badge badge-${r.model_class}`}>{r.model_class}</span>
                  </td>
                  <td>{r.max_tokens}</td>
                  <td>{r.fallback || "–"}</td>
                  <td className="muted">{r.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <section className="box">
        <h3>Recent calls</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Step</th>
                <th>Class</th>
                <th>Status</th>
                <th>Latency</th>
                <th>Tokens</th>
                <th>Reason / error</th>
              </tr>
            </thead>
            <tbody>
              {data?.recent.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{new Date(c.ts * 1000).toLocaleTimeString()}</td>
                  <td className="mono">{c.step}</td>
                  <td>
                    <span className={`badge badge-${c.cache_hit ? "cache" : c.model_class}`}>
                      {c.cache_hit ? "cache" : c.model_class}
                    </span>
                    {c.fell_back ? <span className="badge badge-warn">fallback</span> : null}
                  </td>
                  <td>{c.status == null ? "–" : c.status === -1 ? "simulated" : c.status}</td>
                  <td>{fmtMs(c.latency_ms)}</td>
                  <td>{c.prompt_tokens != null ? `${c.prompt_tokens}/${c.completion_tokens ?? 0}` : "–"}</td>
                  <td className="muted">{c.error || c.route_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
