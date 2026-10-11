import { lazy, Suspense } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { EmptyState } from "./components/EmptyState";
import { Loading } from "./components/Loading";

// Each page is its own chunk, so the chart library only loads with the Overview.
const Overview = lazy(() => import("./pages/Overview"));
const Ingestion = lazy(() => import("./pages/Ingestion"));
const Records = lazy(() => import("./pages/Records"));
const Exceptions = lazy(() => import("./pages/Exceptions"));
const ExceptionDetail = lazy(() => import("./pages/ExceptionDetail"));
const Reconciliations = lazy(() => import("./pages/Reconciliations"));
const ReconciliationDetail = lazy(() => import("./pages/ReconciliationDetail"));
const SourceHealth = lazy(() => import("./pages/SourceHealth"));

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/ingestion", label: "Ingestion" },
  { to: "/records", label: "Records" },
  { to: "/exceptions", label: "Exceptions" },
  { to: "/reconciliations", label: "Reconciliation" },
  { to: "/sources", label: "Source health" },
];

export default function App() {
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <p className="demo-banner">Demo data is synthetic. Not connected to any real facility.</p>
      <div className="layout">
        <header className="sidebar">
          <div className="brand">RecyTrack</div>
          <nav aria-label="Main">
            <ul>
              {NAV.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.end}>
                    {item.label}
                  </NavLink>
                </li>
              ))}
              <li>
                <a href="/docs" target="_blank" rel="noreferrer">
                  API docs ↗
                </a>
              </li>
            </ul>
          </nav>
        </header>
        <main id="main" className="content">
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/ingestion" element={<Ingestion />} />
              <Route path="/records" element={<Records />} />
              <Route path="/exceptions" element={<Exceptions />} />
              <Route path="/exceptions/:eventId" element={<ExceptionDetail />} />
              <Route path="/reconciliations" element={<Reconciliations />} />
              <Route path="/reconciliations/:id" element={<ReconciliationDetail />} />
              <Route path="/sources" element={<SourceHealth />} />
              <Route
                path="*"
                element={
                  <EmptyState>
                    Page not found. <NavLink to="/">Go to the overview.</NavLink>
                  </EmptyState>
                }
              />
            </Routes>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
