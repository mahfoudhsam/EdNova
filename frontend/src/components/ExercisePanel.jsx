import { useEffect, useState } from "react";

export default function ExercisePanel({ state, members, me, send }) {
  const [exercises, setExercises] = useState([]);
  useEffect(() => {
    fetch("/api/exercises")
      .then((r) => r.json())
      .then(setExercises)
      .catch(() => {});
  }, []);
  if (!state) return <aside className="panel" />;

  const ex = state.exercise;
  const total = members.reduce((a, m) => a + m.messages, 0) || 1;

  return (
    <aside className="panel">
      <div className="panel-block">
        <label className="eyebrow" htmlFor="ex-select">Exercise</label>
        <select
          id="ex-select"
          value={ex.id}
          onChange={(e) => send({ type: "set_exercise", exercise_id: e.target.value })}
        >
          {exercises.map((x) => (
            <option key={x.id} value={x.id}>
              {x.title}
            </option>
          ))}
        </select>
        <p className="statement">{ex.statement}</p>
      </div>

      <div className="panel-block">
        <div className="eyebrow">Steps</div>
        <ol className="steps">
          {ex.steps.map((s, i) => (
            <li key={i} className={i === state.step_index ? "current" : i < state.step_index ? "done" : ""}>
              <button onClick={() => send({ type: "set_step", step_index: i })}>{s.goal}</button>
            </li>
          ))}
        </ol>
        <div className="step-nav">
          <button
            className="btn small"
            disabled={state.step_index === 0}
            onClick={() => send({ type: "set_step", step_index: state.step_index - 1 })}
          >
            ← Previous
          </button>
          <button
            className="btn small"
            disabled={state.step_index >= ex.steps.length - 1}
            onClick={() => send({ type: "set_step", step_index: state.step_index + 1 })}
          >
            Next step →
          </button>
        </div>
      </div>

      <div className="panel-block">
        <div className="eyebrow">Room {state.room_id} · talk share</div>
        <ul className="members">
          {members.map((m) => (
            <li key={m.id}>
              <span className="who">
                {m.label}
                {me && m.id === me.id ? " (you)" : ""}
              </span>
              <span className="bar">
                <span style={{ width: `${Math.round((m.messages / total) * 100)}%` }} />
              </span>
              <span className="count">{m.messages}</span>
            </li>
          ))}
        </ul>
        <p className="hint-text">Share the room code so classmates can join.</p>
      </div>
    </aside>
  );
}
