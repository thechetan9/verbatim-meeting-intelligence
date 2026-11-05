"use client";

import dynamic from "next/dynamic";

// The app is an interactive tool with browser-only state (chat history in localStorage),
// so it renders on the client only. There is nothing useful to pre-render on the server.
const App = dynamic(() => import("@/components/App"), {
  ssr: false,
  loading: () => <div className="h-dvh bg-bg" />,
});

export default function Home() {
  return <App />;
}
