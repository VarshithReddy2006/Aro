import React from "react";
import { createRoot } from "react-dom/client";

function App() {
  return (
    <main style={{ fontFamily: "system-ui", padding: 40 }}>
      <h1>ParcelProof</h1>
      <p>Ring-triggered, human-approved operational case system.</p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
