import { useCallback, useEffect, useRef, useState } from "react";

// Connects to /ws/rooms/:id and keeps the room state in React.
export function useRoom(roomId) {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const [me, setMe] = useState(null);
  const [state, setState] = useState(null);
  const [members, setMembers] = useState([]);
  const [feed, setFeed] = useState([]);
  const [aiStatus, setAiStatus] = useState(null); // {kind, label, since, ...}
  const [banner, setBanner] = useState(null);

  useEffect(() => {
    let closedByUs = false;
    let retry;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/rooms/${roomId}`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closedByUs) retry = setTimeout(connect, 1500);
      };
      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        switch (ev.type) {
          case "welcome":
            setMe(ev.you);
            setState(ev.state);
            setMembers(ev.state.members);
            setFeed(ev.history || []);
            break;
          case "state":
            setState(ev.state);
            break;
          case "members":
            setMembers(ev.members);
            break;
          case "message":
          case "ai_message":
          case "ai_error":
          case "system":
            setFeed((f) => [...f, ev].slice(-200));
            break;
          case "ai_status":
            setAiStatus((prev) =>
              ev.kind === "done" ? null : { ...ev, since: ev.kind === "start" || !prev ? Date.now() : prev.since }
            );
            break;
          case "banner":
            setBanner({ ...ev, at: Date.now() });
            break;
          case "error":
            setFeed((f) => [...f, { type: "ai_error", text: ev.text }]);
            break;
          default:
        }
      };
    };

    connect();
    return () => {
      closedByUs = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, [roomId]);

  const send = useCallback((payload) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }, []);

  return { connected, me, state, members, feed, aiStatus, banner, setBanner, send };
}
