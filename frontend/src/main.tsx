import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false },
  },
});

class RootErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { err: Error | null }
> {
  state: { err: Error | null } = { err: null };

  static getDerivedStateFromError(err: unknown) {
    return { err: err instanceof Error ? err : new Error(String(err)) };
  }

  render() {
    if (this.state.err) {
      return (
        <main className="container" style={{ padding: 24, maxWidth: 640 }}>
          <h1 style={{ color: "#ff8f8f" }}>Something broke</h1>
          <p style={{ color: "#98a4d4" }}>{this.state.err.message}</p>
          <p style={{ color: "#98a4d4", fontSize: 14 }}>
            Open DevTools (F12) → Console for the full stack trace. After fixing, hard-refresh the page.
          </p>
        </main>
      );
    }
    return this.props.children;
  }
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error('Missing #root element in index.html');
}

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </RootErrorBoundary>
  </React.StrictMode>,
);
