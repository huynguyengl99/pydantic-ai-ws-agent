import { createClient } from "@chanx-js/client";
import { ChanxClientProvider } from "@chanx-js/client/react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { SERVER } from "./lib/server";
import "./styles.css";

const client = createClient({ baseUrl: `ws://${SERVER}` });

createRoot(document.getElementById("root")!).render(
  <ChanxClientProvider value={client}>
    <App />
  </ChanxClientProvider>,
);
