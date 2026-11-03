"use client";
import { useCallback, useEffect, useState, useRef } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Database,
  FileText,
  FolderOpen,
  LayoutDashboard,
  ScanLine,
  Settings,
  ShieldCheck,
  UploadCloud,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
type Job = {
  id: number;
  status: string;
  engine: string;
  error: string;
  preprocessing: Record<string, boolean>;
};
type Doc = {
  id: number;
  filename: string;
  pages: number;
  status: string;
  created_at: string;
  job: Job | null;
};
type Review = {
  classification: string;
  actor: string;
  reason: string;
  source: string;
};
type Finding = {
  id: number;
  page: number;
  source_text: string;
  normalized_name: string;
  classification: string;
  confidence: number;
  bbox: number[][];
  engine: string;
  is_material: boolean;
  match_score: number;
  method: string;
  explanation: string;
  reference: Record<string, unknown>;
  review: Review | null;
};
type Analysis = {
  job: Job;
  findings: Finding[];
  pages: { number: number; width: number; height: number }[];
};
type Material = {
  id: number;
  standard_name: string;
  aliases: string;
  category: string;
  asbestos_status: string;
  verification_status: string;
  source: string;
  conditions: string;
  description: string;
  manufacturer: string;
};
type Stats = {
  documents: number;
  pages: number;
  materials: number;
  classifications: Record<string, number>;
  categories: Record<string, number>;
  confidence: number[];
  processing: Record<string, number>;
};
const labels: Record<string, string> = {
  ASBESTOS_CONTAINING: "Asbestos containing",
  NON_ASBESTOS: "Non asbestos",
  MANUAL_REVIEW: "Manual review",
};
const colors: Record<string, string> = {
  ASBESTOS_CONTAINING: "#d34b53",
  NON_ASBESTOS: "#1a8a70",
  MANUAL_REVIEW: "#c48a25",
};
const blank = {
  standard_name: "",
  aliases: "",
  category: "",
  asbestos_status: "UNKNOWN",
  verification_status: "UNVERIFIED",
  source: "",
  conditions: "",
  description: "",
  manufacturer: "",
};
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, options);
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw Error(
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail),
    );
  }
  return response.json();
}
function Badge({ value }: { value: string }) {
  return (
    <span className={"badge " + value.toLowerCase()}>
      {labels[value] || value.replaceAll("_", " ")}
    </span>
  );
}
function pct(value: number) {
  return (value * 100).toFixed(0) + "%";
}
function Comparison({ documentId }: { documentId: number }) {
  const [runs, setRuns] = useState<Record<string, Analysis | null>>({}),
    [error, setError] = useState("");
  useEffect(() => {
    api<{ engines: Record<string, Analysis | null> }>("/ocr/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId }),
    })
      .then((data) => setRuns(data.engines))
      .catch((e) => setError(e.message));
  }, [documentId]);
  return (
    <section className="card evidence">
      <div className="card-title">
        <h2>OCR engine comparison</h2>
        <span>Latest completed run per engine</span>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="evidence-grid">
        {["easyocr", "paddleocr"].map((engine) => (
          <div key={engine}>
            <h3>{engine === "easyocr" ? "EasyOCR" : "PaddleOCR"}</h3>
            {runs[engine] ? (
              <>
                <p>
                  Analysis #{runs[engine]!.job.id} ·{" "}
                  {JSON.stringify(runs[engine]!.job.preprocessing)}
                </p>
                {runs[engine]!.findings.map((f) => (
                  <div className="comparison-line" key={f.id}>
                    <b>
                      Page {f.page} · {pct(f.confidence)}
                    </b>
                    <p>{f.source_text}</p>
                  </div>
                ))}
              </>
            ) : (
              <p>
                Run an analysis with this engine to compare its recognized
                annotations and confidence.
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
export default function Home() {
  const [tab, setTab] = useState("Dashboard"),
    [docs, setDocs] = useState<Doc[]>([]),
    [stats, setStats] = useState<Stats | null>(null),
    [materials, setMaterials] = useState<Material[]>([]),
    [selected, setSelected] = useState<Doc | null>(null),
    [analysis, setAnalysis] = useState<Analysis | null>(null),
    [history, setHistory] = useState<Job[]>([]),
    [active, setActive] = useState<Finding | null>(null),
    [page, setPage] = useState(1),
    [zoom, setZoom] = useState(1),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [progress, setProgress] = useState(0),
    [engine, setEngine] = useState("easyocr"),
    [config, setConfig] = useState({
      denoise: false,
      contrast: false,
      threshold: false,
    }),
    [form, setForm] = useState(blank),
    [editId, setEditId] = useState<number | null>(null),
    [runtime, setRuntime] = useState<Record<string, unknown>>({}),
    [reason, setReason] = useState(""),
    [source, setSource] = useState(""),
    [decision, setDecision] = useState("MANUAL_REVIEW");
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [loginUsername, setLoginUsername] = useState("reviewer");
  const [loginPassword, setLoginPassword] = useState("");
  const [authRequired, setAuthRequired] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  useEffect(() => {
    if (!active || active.page !== page || !canvasRef.current) return;
    const xs = active.bbox.map((p) => p[0]),
      ys = active.bbox.map((p) => p[1]);
    const canvas = canvasRef.current;
    canvas.scrollTo({
      left: Math.max(
        0,
        ((Math.min(...xs) + Math.max(...xs)) / 2) * zoom * 0.4 -
          canvas.clientWidth / 2,
      ),
      top: Math.max(
        0,
        ((Math.min(...ys) + Math.max(...ys)) / 2) * zoom * 0.4 -
          canvas.clientHeight / 2,
      ),
      behavior: "smooth",
    });
  }, [active, page, zoom]);
  const refresh = useCallback(async () => {
    try {
      const session = await api<{
        authenticated: boolean;
        authentication_required: boolean;
      }>("/session");
      setAuthenticated(session.authenticated);
      setAuthRequired(session.authentication_required);
      if (!session.authenticated) return;
      const [d, s, m, r] = await Promise.all([
        api<Doc[]>("/documents"),
        api<Stats>("/dashboard/stats"),
        api<Material[]>("/materials"),
        api<Record<string, unknown>>("/settings"),
      ]);
      setDocs(d);
      setStats(s);
      setMaterials(m);
      setRuntime(r);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);
  const open = useCallback(async (d: Doc, jobId?: number) => {
    try {
      setSelected(d);
      const [a, h] = await Promise.all([
        api<Analysis>(
          "/documents/" + d.id + "/results" + (jobId ? "?job_id=" + jobId : ""),
        ),
        api<Job[]>("/documents/" + d.id + "/history"),
      ]);
      setAnalysis(a);
      setHistory(h);
      setActive(null);
      setPage(1);
      setZoom(1);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    if (
      !selected ||
      !analysis ||
      !["QUEUED", "PROCESSING"].includes(analysis.job.status)
    )
      return;
    const timer = setInterval(() => open(selected, analysis.job.id), 2500);
    return () => clearInterval(timer);
  }, [selected, analysis, open]);
  async function upload(files: FileList | null) {
    if (!files?.length || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      for (const file of Array.from(files)) {
        const data = new FormData();
        data.append("file", file);
        await new Promise<void>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", "/api/documents/upload");
          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable)
              setProgress(Math.round((e.loaded / e.total) * 100));
          };
          xhr.onload = () =>
            xhr.status < 300 ? resolve() : reject(Error(xhr.responseText));
          xhr.onerror = () => reject(Error("Upload connection failed"));
          xhr.send(data);
        });
      }
      setNotice("Drawings uploaded. Analysis is queued for the worker.");
      setTab("Documents");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      setProgress(0);
    }
  }
  async function process() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const d = await api<Doc>("/documents/" + selected.id + "/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine, ...config }),
      });
      await open(d);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function saveMaterial(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/materials" + (editId ? "/" + editId : ""), {
        method: editId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      setForm(blank);
      setEditId(null);
      setNotice(
        "Reference saved. Previous analyses retain their original reference snapshot.",
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function review(e: React.FormEvent) {
    e.preventDefault();
    if (!active) return;
    setBusy(true);
    try {
      await api("/reviews", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          finding_id: active.id,
          classification: decision,
          reason,
          source,
        }),
      });
      setNotice("Review recorded in the audit history.");
      setReason("");
      setSource("");
      if (selected) await open(selected, analysis?.job.id);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const navigation = [
    ["Dashboard", LayoutDashboard],
    ["Documents", FolderOpen],
    ["OCR comparison", ScanLine],
    ["Material database", Database],
    ["Manual review", ShieldCheck],
    ["Reports", FileText],
    ["Settings", Settings],
  ] as const;
  const navigate = (value: string) => {
    setTab(value);
    setSelected(null);
    setAnalysis(null);
    setActive(null);
    setError("");
    setNotice("");
  };
  const currentPage = analysis?.pages.find((p) => p.number === page);
  if (authenticated === false)
    return (
      <div className="login-page">
        <form
          className="card login-card"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api("/session", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  username: loginUsername,
                  password: loginPassword,
                }),
              });
              setLoginPassword("");
              await refresh();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <ScanLine size={35} />
          <h1>Drawing Intelligence</h1>
          <p>Sign in to your review workspace.</p>
          <label>
            Username
            <input
              autoComplete="username"
              required
              value={loginUsername}
              onChange={(e) => setLoginUsername(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
            />
          </label>
          {error && (
            <p role="alert" className="failure">
              {error}
            </p>
          )}
          <button className="button primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="/">
          <span className="brand-icon">
            <ScanLine size={25} />
          </span>
          <span>
            Drawing<span className="brand-sub">Intelligence</span>
          </span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav>
          {navigation.map(([name, Icon]) => (
            <button
              key={name}
              className={tab === name ? "nav active" : "nav"}
              onClick={() => navigate(name)}
            >
              <Icon size={18} />
              {name}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <ShieldCheck size={18} />
          <div>
            Evidence first<small>Every decision stays traceable</small>
          </div>
        </div>
      </aside>
      <div className="main-area">
        <header>
          <div className="breadcrumb">
            Workspace <ChevronRight size={14} /> <b>{tab}</b>
          </div>
          <span className="local">
            <span /> {String(runtime.environment || "Connecting")}
            {authRequired && (
              <button
                className="button"
                onClick={async () => {
                  await api("/session", { method: "DELETE" });
                  setSelected(null);
                  setAnalysis(null);
                  setDocs([]);
                  setStats(null);
                  setAuthenticated(false);
                }}
              >
                Sign out
              </button>
            )}
          </span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <p className="eyebrow">ENGINEERING DRAWING INTELLIGENCE</p>
              <h1>
                {selected
                  ? selected.filename
                  : tab === "Dashboard"
                    ? "Drawing intelligence, at a glance."
                    : tab}
              </h1>
              <p className="subtitle">
                {selected
                  ? "Inspect source annotations, verify evidence, and record decisions."
                  : tab === "Dashboard"
                    ? "A clear view of your drawings, material findings, and review queue."
                    : "Manage your analysis workflow and its supporting evidence."}
              </p>
            </div>
            <label className={"button primary " + (busy ? "disabled" : "")}>
              <UploadCloud size={17} />
              {busy ? "Uploading " + progress + "%" : "Upload drawings"}
              <input
                aria-label="Upload drawings"
                disabled={busy}
                type="file"
                multiple
                accept=".pdf,.png,.jpg,.jpeg"
                onChange={(e) => upload(e.target.files)}
              />
            </label>
          </div>
          {error && (
            <div role="alert" className="alert error">
              <b>Action needs attention.</b> {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                ×
              </button>
            </div>
          )}
          {notice && (
            <div role="status" className="alert success">
              {notice}
              <button aria-label="Dismiss notice" onClick={() => setNotice("")}>
                ×
              </button>
            </div>
          )}
          {!selected && tab === "Dashboard" && (
            <>
              <div className="metrics">
                {[
                  ["Documents", stats?.documents, FolderOpen],
                  ["Pages uploaded", stats?.pages, FileText],
                  ["Material entries", stats?.materials, Database],
                  [
                    "Awaiting review",
                    stats?.classifications.MANUAL_REVIEW,
                    ShieldCheck,
                  ],
                ].map(([title, value, Icon]) => {
                  const I = Icon as typeof FolderOpen;
                  return (
                    <div className="metric" key={String(title)}>
                      <div>
                        {String(title)}
                        <I size={18} />
                      </div>
                      <strong>
                        {value === undefined ? "—" : String(value)}
                      </strong>
                      <small>
                        {title === "Awaiting review"
                          ? "Completed analyses needing a decision"
                          : "Across your drawing workspace"}
                      </small>
                    </div>
                  );
                })}
              </div>
              <div className="overview-grid">
                <section className="card distribution">
                  <div className="card-title">
                    <h2>Material classification</h2>
                    <span>Completed analyses</span>
                  </div>
                  <div className="distribution-content">
                    <div
                      className="donut"
                      style={{
                        background:
                          stats && stats.materials
                            ? donut(stats.classifications)
                            : "#e9edf3",
                      }}
                    >
                      <div>
                        <b>{stats?.materials || 0}</b>
                        <span>material entries</span>
                      </div>
                    </div>
                    <div className="legend">
                      {Object.entries(labels).map(([key, label]) => (
                        <div key={key}>
                          <i style={{ background: colors[key] }} />
                          <span>{label}</span>
                          <b>{stats?.classifications[key] || 0}</b>
                        </div>
                      ))}
                    </div>
                  </div>
                  <p className="card-note">
                    Reviewed decisions are shown when available.
                  </p>
                </section>
                <section className="card">
                  <div className="card-title">
                    <h2>Processing activity</h2>
                    <Activity size={17} />
                  </div>
                  <div className="processing-list">
                    {Object.entries(
                      stats?.processing || {
                        QUEUED: 0,
                        PROCESSING: 0,
                        COMPLETE: 0,
                        FAILED: 0,
                      },
                    ).map(([key, value]) => (
                      <div key={key}>
                        <Badge value={key} />
                        <b>{value}</b>
                      </div>
                    ))}
                  </div>
                  <div className="confidence">
                    <small>OCR CONFIDENCE DISTRIBUTION</small>
                    <div className="bars">
                      {(stats?.confidence || [0, 0, 0, 0, 0]).map((n, i) => (
                        <div key={i} title={n + " entries"}>
                          <span
                            style={{
                              height: Math.max(
                                3,
                                (n /
                                  Math.max(1, ...(stats?.confidence || []))) *
                                  55,
                              ),
                            }}
                          />
                          <small>
                            {i * 20}–{(i + 1) * 20}
                          </small>
                        </div>
                      ))}
                    </div>
                  </div>
                </section>
              </div>
              <section className="card categories">
                <div className="card-title">
                  <h2>Material categories</h2>
                  <span>Completed analyses</span>
                </div>
                <div className="category-bars">
                  {Object.entries(stats?.categories || {}).map(
                    ([category, count]) => (
                      <div key={category}>
                        <span>{category}</span>
                        <div>
                          <i
                            style={{
                              width:
                                (count /
                                  Math.max(
                                    1,
                                    ...Object.values(stats?.categories || {}),
                                  )) *
                                  100 +
                                "%",
                            }}
                          />
                        </div>
                        <b>{count}</b>
                      </div>
                    ),
                  )}
                  {!Object.keys(stats?.categories || {}).length && (
                    <p>Category counts appear after materials are extracted.</p>
                  )}
                </div>
              </section>
              <section
                className="upload-banner"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  upload(e.dataTransfer.files);
                }}
              >
                <div className="upload-symbol">
                  <UploadCloud size={25} />
                </div>
                <div>
                  <h2>Turn a drawing into evidence.</h2>
                  <p>
                    Drop drawings here, or upload PDF, PNG, and JPEG files to
                    start an analysis.
                  </p>
                </div>
                <span>
                  Up to {String(runtime.max_upload_mb || 50)} MB / file
                </span>
              </section>
            </>
          )}
          {!selected &&
            [
              "Dashboard",
              "Documents",
              "Reports",
              "Manual review",
              "OCR comparison",
            ].includes(tab) && (
              <section className="card documents">
                <div className="card-title">
                  <h2>
                    {tab === "Dashboard"
                      ? "Recent drawings"
                      : tab === "Manual review"
                        ? "Select a drawing to review"
                        : tab === "OCR comparison"
                          ? "Select a drawing to compare OCR engines"
                          : "Drawing workspace"}
                  </h2>
                  <span>{docs.length} drawings</span>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>DRAWING</th>
                        <th>PAGES</th>
                        <th>STATUS</th>
                        <th>UPLOADED</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {docs.map((d) => (
                        <tr key={d.id}>
                          <td>
                            <button
                              className="file-link"
                              onClick={() => open(d)}
                            >
                              <span className="file-type">
                                <FileText size={18} />
                              </span>
                              <div>
                                <b>{d.filename}</b>
                                <small>
                                  Drawing #{String(d.id).padStart(4, "0")} ·{" "}
                                  {d.job?.engine}
                                </small>
                              </div>
                            </button>
                          </td>
                          <td>{d.pages}</td>
                          <td>
                            <Badge value={d.status} />
                          </td>
                          <td>
                            {new Date(d.created_at + "Z").toLocaleDateString()}
                          </td>
                          <td>
                            <button
                              className="icon-button"
                              aria-label={"Open " + d.filename}
                              onClick={() => open(d)}
                            >
                              <ArrowUpRight size={18} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!docs.length && (
                  <div className="empty">
                    <FolderOpen size={32} />
                    <h3>Your drawing workspace starts here.</h3>
                    <p>
                      Upload a drawing to extract annotations and identify
                      material references.
                    </p>
                  </div>
                )}
              </section>
            )}
          {selected && (
            <>
              <button
                className="back"
                onClick={() => {
                  setSelected(null);
                  setAnalysis(null);
                  setActive(null);
                }}
              >
                <ArrowLeft size={16} /> Back to drawings
              </button>
              <section className="card analysis-controls">
                <div>
                  <Badge value={analysis?.job.status || selected.status} />
                  <span>
                    {" "}
                    {selected.pages} pages · Analysis #{analysis?.job.id}
                  </span>
                  {analysis?.job.error && (
                    <p className="failure">{analysis.job.error}</p>
                  )}
                </div>
                <div className="controls">
                  <label>
                    Engine
                    <select
                      value={engine}
                      onChange={(e) => setEngine(e.target.value)}
                    >
                      <option value="easyocr">EasyOCR</option>
                      <option value="paddleocr">PaddleOCR</option>
                      <option value="auto">Automatic fallback</option>
                    </select>
                  </label>
                  {Object.entries(config).map(([key, value]) => (
                    <label className="check" key={key}>
                      <input
                        type="checkbox"
                        checked={value}
                        onChange={(e) =>
                          setConfig({ ...config, [key]: e.target.checked })
                        }
                      />
                      {key}
                    </label>
                  ))}
                  <button
                    className="button"
                    disabled={
                      busy ||
                      ["QUEUED", "PROCESSING"].includes(
                        analysis?.job.status || "",
                      )
                    }
                    onClick={process}
                  >
                    Run analysis
                  </button>
                </div>
              </section>
              <div className="history">
                {history.map((h) => (
                  <button
                    className={analysis?.job.id === h.id ? "selected" : ""}
                    key={h.id}
                    onClick={() => open(selected, h.id)}
                  >
                    #{h.id} {h.engine} <Badge value={h.status} />
                  </button>
                ))}
              </div>
              {analysis?.job.status === "COMPLETE" && (
                <div className="report-actions">
                  <a
                    className="button"
                    href={
                      "/api/documents/" +
                      selected.id +
                      "/report?job_id=" +
                      analysis.job.id
                    }
                  >
                    Download PDF report <ArrowUpRight size={15} />
                  </a>
                  <a
                    className="button"
                    href={
                      "/api/documents/" +
                      selected.id +
                      "/report?format=csv&job_id=" +
                      analysis.job.id
                    }
                  >
                    Export CSV
                  </a>
                  <span>
                    {analysis.findings.filter((f) => f.is_material).length}{" "}
                    materials · {analysis.findings.length} OCR annotations
                  </span>
                </div>
              )}
              <div className="viewer-grid">
                <section className="card viewer">
                  <div className="viewer-toolbar">
                    <div>
                      <button
                        aria-label="Previous page"
                        disabled={page <= 1}
                        onClick={() => setPage(page - 1)}
                      >
                        <ChevronLeft size={18} />
                      </button>
                      <span>
                        Page {page} / {selected.pages}
                      </span>
                      <button
                        aria-label="Next page"
                        disabled={page >= selected.pages}
                        onClick={() => setPage(page + 1)}
                      >
                        <ChevronRight size={18} />
                      </button>
                    </div>
                    <div>
                      <button
                        aria-label="Zoom out"
                        onClick={() => setZoom(Math.max(0.5, zoom - 0.25))}
                      >
                        <ZoomOut size={18} />
                      </button>
                      <span>{Math.round(zoom * 100)}%</span>
                      <button
                        aria-label="Zoom in"
                        onClick={() => setZoom(Math.min(4, zoom + 0.25))}
                      >
                        <ZoomIn size={18} />
                      </button>
                    </div>
                  </div>
                  <div
                    className="canvas"
                    ref={canvasRef}
                    onPointerDown={(e) => {
                      if ((e.target as Element).closest("polygon")) return;
                      dragRef.current = {
                        x: e.clientX,
                        y: e.clientY,
                        left: e.currentTarget.scrollLeft,
                        top: e.currentTarget.scrollTop,
                      };
                      e.currentTarget.setPointerCapture(e.pointerId);
                    }}
                    onPointerMove={(e) => {
                      if (!dragRef.current) return;
                      e.currentTarget.scrollLeft =
                        dragRef.current.left - (e.clientX - dragRef.current.x);
                      e.currentTarget.scrollTop =
                        dragRef.current.top - (e.clientY - dragRef.current.y);
                    }}
                    onPointerUp={() => {
                      dragRef.current = null;
                    }}
                    onPointerCancel={() => {
                      dragRef.current = null;
                    }}
                  >
                    {currentPage ? (
                      <svg
                        role="img"
                        aria-label={"Drawing page " + page}
                        width={currentPage.width * zoom * 0.4}
                        height={currentPage.height * zoom * 0.4}
                        viewBox={
                          "0 0 " + currentPage.width + " " + currentPage.height
                        }
                      >
                        <image
                          href={
                            "/api/documents/" +
                            selected.id +
                            "/pages/" +
                            page +
                            "?job_id=" +
                            analysis?.job.id
                          }
                          width={currentPage.width}
                          height={currentPage.height}
                        />
                        {analysis?.findings
                          .filter((f) => f.page === page)
                          .map((f) => (
                            <polygon
                              role="button"
                              tabIndex={0}
                              aria-label={f.source_text}
                              key={f.id}
                              points={f.bbox.map((p) => p.join(",")).join(" ")}
                              fill={
                                active?.id === f.id
                                  ? "#2563eb44"
                                  : "transparent"
                              }
                              stroke={
                                colors[
                                  f.review?.classification || f.classification
                                ]
                              }
                              strokeWidth={active?.id === f.id ? 5 : 2}
                              onClick={() => setActive(f)}
                              onKeyDown={(e) =>
                                e.key === "Enter" && setActive(f)
                              }
                            />
                          ))}
                      </svg>
                    ) : (
                      <div className="empty">
                        <ScanLine size={35} />
                        <h3>
                          {analysis?.job.status === "FAILED"
                            ? "Analysis interrupted"
                            : "Preparing drawing pages"}
                        </h3>
                        <p>
                          {analysis?.job.status === "FAILED"
                            ? "Inspect the failure details above and retry the analysis."
                            : "Keep the worker running to process this drawing."}
                        </p>
                      </div>
                    )}
                  </div>
                </section>
                <section className="card findings">
                  <div className="card-title">
                    <h2>Material findings</h2>
                    <span>
                      {analysis?.findings.filter((f) => f.is_material).length ||
                        0}
                    </span>
                  </div>
                  <div className="finding-list">
                    {analysis?.findings
                      .filter((f) => f.is_material)
                      .map((f) => (
                        <button
                          key={f.id}
                          className={
                            "finding " + (active?.id === f.id ? "chosen" : "")
                          }
                          onClick={() => {
                            setActive(f);
                            setPage(f.page);
                          }}
                        >
                          <Badge
                            value={f.review?.classification || f.classification}
                          />
                          <h3>{f.normalized_name}</h3>
                          <p>{f.source_text}</p>
                          <small>
                            Page {f.page} · OCR {pct(f.confidence)} · {f.method}{" "}
                            match {pct(f.match_score)}
                          </small>
                        </button>
                      ))}
                    {!analysis?.findings.some((f) => f.is_material) && (
                      <div className="empty">
                        <p>
                          No material findings yet. Empty results do not
                          establish asbestos absence.
                        </p>
                      </div>
                    )}
                  </div>
                </section>
              </div>
              {active && (
                <section className="card evidence">
                  <div className="card-title">
                    <h2>Finding #{active.id} · Evidence and review</h2>
                    <Badge value={active.classification} />
                  </div>
                  <div className="evidence-grid">
                    <div>
                      <h3>Original AI result</h3>
                      <p>{active.explanation}</p>
                      <dl>
                        <dt>Source annotation</dt>
                        <dd>{active.source_text}</dd>
                        <dt>Engine / confidence</dt>
                        <dd>
                          {active.engine} / {pct(active.confidence)}
                        </dd>
                        <dt>Reference snapshot</dt>
                        <dd>
                          <pre>{JSON.stringify(active.reference, null, 2)}</pre>
                        </dd>
                        <dt>Coordinates</dt>
                        <dd>{JSON.stringify(active.bbox)}</dd>
                      </dl>
                      {active.review && (
                        <div className="alert success">
                          Latest review: {labels[active.review.classification]}{" "}
                          by {active.review.actor}. {active.review.reason}{" "}
                          Source: {active.review.source}
                        </div>
                      )}
                    </div>
                    <form onSubmit={review}>
                      <h3>Record a review decision</h3>
                      <label>
                        Classification
                        <select
                          value={decision}
                          onChange={(e) => setDecision(e.target.value)}
                        >
                          {Object.entries(labels).map(([key, label]) => (
                            <option key={key} value={key}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Reason
                        <textarea
                          required
                          minLength={10}
                          maxLength={4000}
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                        />
                      </label>
                      <label>
                        Evidence source
                        <textarea
                          required
                          minLength={10}
                          maxLength={4000}
                          value={source}
                          onChange={(e) => setSource(e.target.value)}
                        />
                      </label>
                      <button disabled={busy} className="button primary">
                        Save review
                      </button>
                    </form>
                  </div>
                </section>
              )}
            </>
          )}
          {!selected && tab === "Material database" && (
            <div className="catalog-grid">
              <section className="card">
                <div className="card-title">
                  <h2>Reference catalog</h2>
                  <a href="/api/materials/export">Export CSV ↗</a>
                </div>
                <div className="catalog-tools">
                  <label className="button">
                    Import CSV
                    <input
                      type="file"
                      accept=".csv"
                      onChange={async (e) => {
                        if (!e.target.files?.[0]) return;
                        const data = new FormData();
                        data.append("file", e.target.files[0]);
                        try {
                          await api("/materials/import", {
                            method: "POST",
                            body: data,
                          });
                          setNotice(
                            "Imported references require individual verification.",
                          );
                          refresh();
                        } catch (err) {
                          setError((err as Error).message);
                        }
                      }}
                    />
                  </label>
                  <span>Imported records remain unverified.</span>
                </div>
                {materials.map((m) => (
                  <button
                    className="catalog-item"
                    key={m.id}
                    onClick={() => {
                      setEditId(m.id);
                      setForm({
                        standard_name: m.standard_name,
                        aliases: m.aliases,
                        category: m.category,
                        asbestos_status: m.asbestos_status,
                        verification_status: m.verification_status,
                        source: m.source,
                        conditions: m.conditions,
                        description: m.description,
                        manufacturer: m.manufacturer,
                      });
                    }}
                  >
                    <b>{m.standard_name}</b>
                    <Badge value={m.verification_status} />
                    <small>
                      {m.category} · {m.asbestos_status}
                    </small>
                    <p>{m.source}</p>
                  </button>
                ))}
              </section>
              <form className="card material-form" onSubmit={saveMaterial}>
                <h2>
                  {editId ? "Edit reference #" + editId : "Add reference"}
                </h2>
                {[
                  "standard_name",
                  "aliases",
                  "category",
                  "description",
                  "manufacturer",
                  "source",
                  "conditions",
                ].map((key) => (
                  <label key={key}>
                    {key.replaceAll("_", " ")}
                    {["source", "conditions"].includes(key) ? (
                      <textarea
                        required={
                          key === "source" &&
                          form.verification_status === "VERIFIED"
                        }
                        value={form[key as keyof typeof form]}
                        onChange={(e) =>
                          setForm({ ...form, [key]: e.target.value })
                        }
                      />
                    ) : (
                      <input
                        required={key === "standard_name"}
                        value={form[key as keyof typeof form]}
                        onChange={(e) =>
                          setForm({ ...form, [key]: e.target.value })
                        }
                      />
                    )}
                  </label>
                ))}
                <label>
                  Asbestos status
                  <select
                    value={form.asbestos_status}
                    onChange={(e) =>
                      setForm({ ...form, asbestos_status: e.target.value })
                    }
                  >
                    {[
                      "UNKNOWN",
                      "CONTAINS_ASBESTOS",
                      "DOES_NOT_CONTAIN_ASBESTOS",
                      "CONDITION_DEPENDENT",
                    ].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Verification
                  <select
                    value={form.verification_status}
                    onChange={(e) =>
                      setForm({ ...form, verification_status: e.target.value })
                    }
                  >
                    {["UNVERIFIED", "VERIFIED", "DEMONSTRATION"].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <button disabled={busy} className="button primary">
                  Save reference
                </button>
                {editId && (
                  <button
                    type="button"
                    className="button"
                    onClick={() => {
                      setEditId(null);
                      setForm(blank);
                    }}
                  >
                    New reference
                  </button>
                )}
              </form>
            </div>
          )}
          {!selected && tab === "Settings" && (
            <section className="card settings">
              <h2>Processing configuration</h2>
              <p>
                CPU inference is the default. Configure server settings through
                environment variables.
              </p>
              {Object.entries(runtime).map(([key, value]) => (
                <div className="setting" key={key}>
                  <b>{key.replaceAll("_", " ")}</b>
                  <code>{JSON.stringify(value)}</code>
                </div>
              ))}
              <p>
                Japanese: EasyOCR uses <code>ja,en</code>; PaddleOCR uses a
                single <code>ja</code> language setting mapped to its{" "}
                <code>japan</code> model. Models must be provisioned before
                deployment.
              </p>
            </section>
          )}
          {selected && tab === "OCR comparison" && (
            <Comparison key={analysis?.job.id} documentId={selected.id} />
          )}
          <footer>
            <ShieldCheck size={14} /> Decision support · Source verification and
            professional review remain essential.
          </footer>
        </main>
      </div>
    </div>
  );
}
function donut(counts: Record<string, number>) {
  let start = 0;
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return (
    "conic-gradient(" +
    Object.entries(labels)
      .map(([key]) => {
        const end = start + ((counts[key] || 0) / total) * 100;
        const part = colors[key] + " " + start + "% " + end + "%";
        start = end;
        return part;
      })
      .join(",") +
    ")"
  );
}
