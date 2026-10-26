import { useCallback, useEffect, useRef, useState } from "react";
import { useRoom } from "../useRoom.js";
import AiStatus from "../components/AiStatus.jsx";
import ModelBadge from "../components/ModelBadge.jsx";
import ExercisePanel from "../components/ExercisePanel.jsx";

const RTL = /[؀-ۿ]/;

function Message({ ev, me }) {
  if (ev.type === "system") return <div className="sys">{ev.text}</div>;
  if (ev.type === "ai_error") return <div className="msg ai error">{ev.text}</div>;
  const mine = ev.type === "message" && me && ev.from_id === me.id;
  const dir = RTL.test(ev.text) ? "rtl" : "auto";

  if (ev.type === "ai_message") {
    return (
      <div className="msg ai">
        <div className="msg-head">
          <span className="author">EdNova</span>
          {ev.asked_by && <span className="muted">answering {ev.asked_by}</span>}
        </div>
        <div className="msg-body" dir={dir}>{ev.text}</div>
        <ModelBadge msg={ev} />
      </div>
    );
  }
  return (
    <div className={`msg peer ${mine ? "mine" : ""}`}>
      <div className="msg-head">
        <span className="author">{mine ? "You" : ev.from}</span>
      </div>
      <div className="msg-body" dir={dir}>{ev.text}</div>
    </div>
  );
}

function Banner({ banner, onClose }) {
  const [left, setLeft] = useState(banner?.seconds ?? null);
  useEffect(() => {
    if (!banner) return;
    setLeft(banner.seconds ?? null);
    const t = setInterval(() => {
      const elapsed = (Date.now() - banner.at) / 1000;
      if (banner.seconds) setLeft(Math.max(0, Math.ceil(banner.seconds - elapsed)));
      if (elapsed > (banner.seconds ? banner.seconds + 2 : 20)) onClose();
    }, 250);
    return () => clearInterval(t);
  }, [banner, onClose]);
  if (!banner) return null;
  return (
    <div className={`banner banner-${banner.level}`} role="alert">
      <span>{banner.text}</span>
      {left !== null && left > 0 && <strong>{left} s</strong>}
      <button aria-label="Dismiss" onClick={onClose}>×</button>
    </div>
  );
}

export default function RoomPage({ roomId }) {
  const { connected, me, state, members, feed, aiStatus, banner, setBanner, send } = useRoom(roomId);
  const [text, setText] = useState("");
  const feedRef = useRef(null);
  const closeBanner = useCallback(() => setBanner(null), [setBanner]);
  const alone = members.length <= 1;

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [feed.length, aiStatus]);

  const submit = (askAi) => {
    const t = text.trim();
    if (!t) return;
    send({ type: "message", text: t, ask_ai: askAi });
    setText("");
  };

  return (
    <main className="room">
      <ExercisePanel state={state} members={members} me={me} send={send} />

      <section className="chat">
        <div className="chat-head">
          <div>
            <div className="eyebrow">Study room</div>
            <h2>{roomId}</h2>
          </div>
          <span className={`conn ${connected ? "on" : "off"}`}>{connected ? "connected" : "reconnecting…"}</span>
        </div>

        <Banner banner={banner} onClose={closeBanner} />

        <div className="feed" ref={feedRef}>
          {feed.length === 0 && (
            <div className="empty">
              Talk the exercise through with your group. When you are stuck, ask EdNova: you will get a hint
              first, not the answer.
            </div>
          )}
          {feed.map((ev, i) => (
            <Message key={i} ev={ev} me={me} />
          ))}
          <AiStatus status={aiStatus} />
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            submit(alone);
          }}
        >
          <textarea
            value={text}
            placeholder="Write to your group… (Darija, français, عربي, English)"
            rows={2}
            dir="auto"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(alone);
              }
            }}
          />
          <div className="composer-actions">
            {!alone && (
              <button type="button" className="btn" disabled={!text.trim()} onClick={() => submit(false)}>
                Send to group
              </button>
            )}
            <button type="button" className="btn primary" disabled={!text.trim()} onClick={() => submit(true)}>
              Ask EdNova
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
