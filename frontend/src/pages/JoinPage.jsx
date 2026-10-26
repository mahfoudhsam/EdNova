import { useState } from "react";

function randomCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from({ length: 5 }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
}

export default function JoinPage() {
  const [code, setCode] = useState("");

  const go = (c) => {
    const clean = c.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 12);
    if (clean) window.location.hash = `#/room/${clean}`;
  };

  return (
    <main className="join">
      <section className="join-card">
        <h1>Learn together. Ask the AI last.</h1>
        <p className="lead">
          Open a study room, share the code with up to five classmates, and work through an exercise
          together. EdNova gives hints before answers, in Darija, French, Arabic or English.
        </p>
        <div className="join-actions">
          <button className="btn primary" onClick={() => go(randomCode())}>
            Start a new room
          </button>
          <form
            className="join-form"
            onSubmit={(e) => {
              e.preventDefault();
              go(code);
            }}
          >
            <input
              aria-label="Room code"
              placeholder="Room code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              maxLength={12}
            />
            <button className="btn" type="submit" disabled={!code.trim()}>
              Join
            </button>
          </form>
        </div>
        <p className="privacy">
          No account, no names: you appear as “Learner A”, “Learner B”… Only use anonymous or fictional data.
        </p>
      </section>
    </main>
  );
}
