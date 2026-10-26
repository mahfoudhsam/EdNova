import { useEffect, useState } from "react";
import JoinPage from "./pages/JoinPage.jsx";
import RoomPage from "./pages/RoomPage.jsx";
import MetricsPage from "./pages/MetricsPage.jsx";

// Tiny hash router: #/  ·  #/room/CODE  ·  #/metrics
function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.replace(/^#/, "");
}

export default function App() {
  const route = useHashRoute();
  const room = route.match(/^\/room\/([A-Za-z0-9]{1,12})/);

  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">
          Ed<span>Nova</span>
        </a>
        <span className="tagline">Study room · peer learning companion</span>
        <nav>
          <a href="#/" className={route === "/" ? "active" : ""}>Rooms</a>
          <a href="#/metrics" className={route === "/metrics" ? "active" : ""}>Metrics</a>
        </nav>
      </header>
      {room ? (
        <RoomPage key={room[1]} roomId={room[1].toUpperCase()} />
      ) : route === "/metrics" ? (
        <MetricsPage />
      ) : (
        <JoinPage />
      )}
    </div>
  );
}
