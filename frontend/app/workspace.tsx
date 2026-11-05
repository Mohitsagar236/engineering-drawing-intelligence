"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

type DocLike = {
  id: number;
  filename: string;
  pages: number;
  status: string;
  created_at: string;
  project_id: number | null;
  tags: string[];
  job: unknown;
};
export type Project = {
  id: number;
  name: string;
  description: string;
  documents: number;
};
type Tag = { id: number; name: string; documents: number };
export type Filters = {
  q: string;
  status: string;
  project: string;
  tag: string;
};
const noFilters: Filters = { q: "", status: "", project: "", tag: "" };
const classes: Record<string, [string, string]> = {
  ASBESTOS_CONTAINING: ["Asbestos containing", "#d34b53"],
  NON_ASBESTOS: ["Non asbestos", "#1a8a70"],
  MANUAL_REVIEW: ["Manual review", "#c48a25"],
};

export function useCatalog(trigger: unknown) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const reload = useCallback(async () => {
    try {
      const [p, t] = await Promise.all([
        api<Project[]>("/projects"),
        api<Tag[]>("/tags"),
      ]);
      setProjects(Array.isArray(p) ? p : []);
      setTags(Array.isArray(t) ? t : []);
    } catch {
      /* The main refresh loop surfaces connection and session errors. */
    }
  }, []);
  useEffect(() => {
    reload();
  }, [reload, trigger]);
  return { projects, tags, reload };
}

export function useFilteredDocs<T extends DocLike>(
  docs: T[],
  filters: Filters,
): T[] {
  const [found, setFound] = useState<T[] | null>(null);
  const active = Object.values(filters).some((v) => v.trim());
  const key = JSON.stringify(filters);
  useEffect(() => {
    if (!active) return;
    const params = new URLSearchParams({ limit: "200" });
    if (filters.q.trim()) params.set("q", filters.q.trim());
    if (filters.status) params.set("status", filters.status);
    if (filters.project) params.set("project_id", filters.project);
    if (filters.tag) params.set("tag", filters.tag);
    let cancelled = false;
    const timer = setTimeout(() => {
      api<T[]>("/documents?" + params)
        .then((rows) => !cancelled && setFound(rows))
        .catch(() => !cancelled && setFound([]));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // Re-run when the polled workspace changes so statuses stay current.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, active, docs]);
  return active ? (found ?? []) : docs;
}

export function FilterBar({
  filters,
  onChange,
  projects,
  tags,
  shown,
}: {
  filters: Filters;
  onChange: (f: Filters) => void;
  projects: Project[];
  tags: Tag[];
  shown: number;
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  const active = Object.values(filters).some((v) => v.trim());
  return (
    <div className="filter-bar" role="search" aria-label="Filter drawings">
      <input
        type="search"
        aria-label="Search drawings"
        placeholder="Search file names, tags, or recognized text"
        value={filters.q}
        maxLength={200}
        onChange={(e) => set({ q: e.target.value })}
      />
      <select
        aria-label="Filter by status"
        value={filters.status}
        onChange={(e) => set({ status: e.target.value })}
      >
        <option value="">All statuses</option>
        {["QUEUED", "PROCESSING", "COMPLETE", "FAILED"].map((s) => (
          <option key={s} value={s}>
            {s.charAt(0) + s.slice(1).toLowerCase()}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by project"
        value={filters.project}
        onChange={(e) => set({ project: e.target.value })}
      >
        <option value="">All projects</option>
        <option value="-1">No project</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by tag"
        value={filters.tag}
        onChange={(e) => set({ tag: e.target.value })}
      >
        <option value="">All tags</option>
        {tags.map((t) => (
          <option key={t.id} value={t.name}>
            {t.name} ({t.documents})
          </option>
        ))}
      </select>
      {active && (
        <button className="button" onClick={() => onChange(noFilters)}>
          Clear · {shown} match{shown === 1 ? "" : "es"}
        </button>
      )}
    </div>
  );
}

export function BatchBar({
  ids,
  onClear,
  projects,
  onChanged,
}: {
  ids: number[];
  onClear: () => void;
  projects: Project[];
  onChanged: () => void;
}) {
  const [message, setMessage] = useState("");
  if (!ids.length) return null;
  const query = "ids=" + ids.slice(0, 50).join(",");
  const assign = async (value: string) => {
    if (!value) return;
    setMessage("");
    try {
      await Promise.all(
        ids.map((id) =>
          api("/documents/" + id, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              project_id: value === "none" ? null : Number(value),
            }),
          }),
        ),
      );
      setMessage(
        `Updated ${ids.length} drawing${ids.length === 1 ? "" : "s"}.`,
      );
      onChanged();
    } catch (e) {
      setMessage((e as Error).message);
    }
  };
  return (
    <div className="batch-bar" role="region" aria-label="Batch actions">
      <b>{ids.length} selected</b>
      {ids.length > 50 && <span>Exports include the first 50.</span>}
      <a className="button" href={`/api/reports/batch?${query}&format=csv`}>
        Combined CSV
      </a>
      <a className="button" href={`/api/reports/batch?${query}&format=pdf`}>
        PDF reports (ZIP)
      </a>
      <select
        aria-label="Assign selected to project"
        value=""
        onChange={(e) => assign(e.target.value)}
      >
        <option value="">Assign to project…</option>
        <option value="none">Remove from project</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <button className="button" onClick={onClear}>
        Clear selection
      </button>
      {message && <span role="status">{message}</span>}
    </div>
  );
}

export function DocumentMeta({
  doc,
  projects,
  onChanged,
}: {
  doc: DocLike;
  projects: Project[];
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [tags, setTags] = useState(doc.tags ?? []);
  const [project, setProject] = useState(doc.project_id);
  useEffect(() => {
    setTags(doc.tags ?? []);
    setProject(doc.project_id);
  }, [doc.id, doc.tags, doc.project_id]);
  const save = async (patch: {
    project_id?: number | null;
    tags?: string[];
  }) => {
    setError("");
    try {
      await api("/documents/" + doc.id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const addTag = async () => {
    const tag = draft.trim().toLowerCase();
    if (!tag || tags.includes(tag)) return setDraft("");
    const next = [...tags, tag];
    setTags(next);
    setDraft("");
    await save({ tags: next });
  };
  return (
    <section className="card doc-meta" aria-label="Project and tags">
      <label>
        Project
        <select
          value={project ?? ""}
          onChange={(e) => {
            const value = e.target.value ? Number(e.target.value) : null;
            setProject(value);
            save({ project_id: value });
          }}
        >
          <option value="">No project</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <div className="tag-editor">
        <span>Tags</span>
        {tags.map((t) => (
          <button
            key={t}
            className="tag"
            aria-label={"Remove tag " + t}
            onClick={() => {
              const next = tags.filter((x) => x !== t);
              setTags(next);
              save({ tags: next });
            }}
          >
            {t} ×
          </button>
        ))}
        <input
          aria-label="Add tag"
          placeholder="Add tag"
          value={draft}
          maxLength={40}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addTag()}
        />
      </div>
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}

type Source = { finding_id: number; page: number; confidence: number };
type Extraction = {
  note: string;
  title_block: { field: string; value: string; source: Source }[];
  dimensions: {
    text: string;
    kind: string;
    value: number;
    unit: string;
    tolerance: string;
    source: Source;
  }[];
  bom: {
    page: number;
    columns: string[];
    rows: { cells: Record<string, string> }[];
  }[];
};

export function ExtractionPanel({
  documentId,
  jobId,
  onSelect,
}: {
  documentId: number;
  jobId: number;
  onSelect?: (findingId: number) => void;
}) {
  const [data, setData] = useState<Extraction | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError("");
    api<Extraction>(`/documents/${documentId}/extraction?job_id=${jobId}`)
      .then(
        (d) =>
          !cancelled &&
          setData({
            ...d,
            title_block: d.title_block ?? [],
            dimensions: d.dimensions ?? [],
            bom: d.bom ?? [],
          }),
      )
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [documentId, jobId]);
  if (error)
    return (
      <section className="card extraction">
        <p className="error-text">{error}</p>
      </section>
    );
  if (!data)
    return (
      <section className="card extraction">
        <p>Reading drawing structure…</p>
      </section>
    );
  const link = (s: Source, label: string) =>
    onSelect ? (
      <button className="link" onClick={() => onSelect(s.finding_id)}>
        {label}
      </button>
    ) : (
      label
    );
  const kinds = data.dimensions.reduce<Record<string, number>>((acc, d) => {
    acc[d.kind] = (acc[d.kind] || 0) + 1;
    return acc;
  }, {});
  return (
    <section className="card extraction">
      <div className="card-title">
        <h2>Drawing data</h2>
        <a
          className="button"
          href={`/api/documents/${documentId}/extraction?format=csv&job_id=${jobId}`}
        >
          Export CSV
        </a>
      </div>
      <p className="card-note">{data.note}</p>
      <h3>Title block</h3>
      {data.title_block.length ? (
        <dl className="title-block">
          {data.title_block.map((e) => (
            <div key={e.field}>
              <dt>{e.field.replace(/_/g, " ")}</dt>
              <dd>{link(e.source, e.value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>No labelled title block fields were recognized.</p>
      )}
      <h3>
        Dimensions{" "}
        <small>
          {data.dimensions.length} found
          {Object.entries(kinds).map(([k, n]) => ` · ${n} ${k}`)}
        </small>
      </h3>
      {data.dimensions.length ? (
        <div className="table-scroll dimension-list">
          <table>
            <thead>
              <tr>
                <th>VALUE</th>
                <th>TYPE</th>
                <th>UNIT</th>
                <th>TOLERANCE</th>
                <th>PAGE</th>
              </tr>
            </thead>
            <tbody>
              {data.dimensions.map((d) => (
                <tr key={d.source.finding_id}>
                  <td>{link(d.source, d.text)}</td>
                  <td>{d.kind}</td>
                  <td>{d.unit || "—"}</td>
                  <td>{d.tolerance || "—"}</td>
                  <td>{d.source.page}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>No dimension values were recognized.</p>
      )}
      <h3>Bill of materials</h3>
      {data.bom.length ? (
        data.bom.map((t) => (
          <div className="table-scroll" key={t.page}>
            <table aria-label={"Bill of materials, page " + t.page}>
              <thead>
                <tr>
                  {t.columns.map((c) => (
                    <th key={c}>{c.replace(/_/g, " ").toUpperCase()}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {t.rows.map((r, i) => (
                  <tr key={i}>
                    {t.columns.map((c) => (
                      <td key={c}>{r.cells[c] || "—"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))
      ) : (
        <p>No bill of materials table was recognized.</p>
      )}
    </section>
  );
}

type Summary = {
  project: Project;
  documents: number;
  pages: number;
  materials: number;
  classifications: Record<string, number>;
  categories: Record<string, number>;
  confidence: number[];
  processing: Record<string, number>;
  items: (DocLike & { classifications: Record<string, number> })[];
};

function Bars({
  rows,
  label,
}: {
  rows: { name: string; value: number; color?: string }[];
  label: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="bars" role="img" aria-label={label}>
      {rows.map((r) => (
        <div key={r.name}>
          <span>{r.name}</span>
          <i>
            <b
              style={{
                width: (r.value / max) * 100 + "%",
                background: r.color || "#2a60db",
              }}
            />
          </i>
          <em>{r.value}</em>
        </div>
      ))}
    </div>
  );
}

export function ProjectsView({
  projects,
  reload,
  onOpen,
}: {
  projects: Project[];
  reload: () => void;
  onOpen: (id: number) => void;
}) {
  const [current, setCurrent] = useState<number | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const selected = current ?? projects[0]?.id ?? null;
  useEffect(() => {
    if (selected === null) return setSummary(null);
    let cancelled = false;
    api<Summary>(`/projects/${selected}/summary`)
      .then((s) => !cancelled && setSummary(s))
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [selected, projects]);
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const made = await api<Project>("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description }),
      });
      setName("");
      setDescription("");
      setCurrent(made.id);
      reload();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const remove = async () => {
    if (
      !summary ||
      !window.confirm(
        `Delete project "${summary.project.name}"? Its drawings are kept.`,
      )
    )
      return;
    try {
      await api(`/projects/${summary.project.id}`, { method: "DELETE" });
      setCurrent(null);
      setSummary(null);
      reload();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <>
      <form className="card project-form" onSubmit={create}>
        <div className="card-title">
          <h2>New project</h2>
        </div>
        <label>
          Name
          <input
            value={name}
            required
            minLength={2}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          Description
          <input
            value={description}
            maxLength={2000}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <button className="button primary">Create project</button>
        {error && <p className="error-text">{error}</p>}
      </form>
      {!projects.length && (
        <section className="card empty">
          <h3>No projects yet.</h3>
          <p>
            Create a project, then assign drawings to it from a drawing or the
            Documents list.
          </p>
        </section>
      )}
      {!!projects.length && (
        <section className="card project-summary">
          <div className="card-title">
            <label>
              Project{" "}
              <select
                value={selected ?? ""}
                onChange={(e) => setCurrent(Number(e.target.value))}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.documents})
                  </option>
                ))}
              </select>
            </label>
            {summary && (
              <span className="report-actions">
                <a
                  className="button"
                  href={`/api/projects/${summary.project.id}/report?format=pdf`}
                >
                  Summary PDF
                </a>
                <a
                  className="button"
                  href={`/api/projects/${summary.project.id}/report?format=csv`}
                >
                  Findings CSV
                </a>
                <a
                  className="button"
                  href={`/api/projects/${summary.project.id}/report?format=zip`}
                >
                  Reports ZIP
                </a>
                <button className="button" onClick={remove}>
                  Delete project
                </button>
              </span>
            )}
          </div>
          {summary && (
            <>
              <p className="card-note">
                {summary.project.description || "No description."}
              </p>
              <div className="metrics compact">
                {[
                  ["Drawings", summary.documents],
                  ["Pages", summary.pages],
                  ["Material entries", summary.materials],
                  ["Complete", summary.processing.COMPLETE],
                ].map(([k, v]) => (
                  <div className="metric" key={k}>
                    <small>{k}</small>
                    <b>{v}</b>
                  </div>
                ))}
              </div>
              <div className="chart-grid">
                <div>
                  <h3>Classifications</h3>
                  <Bars
                    label="Classification counts"
                    rows={Object.entries(classes).map(([k, [name, color]]) => ({
                      name,
                      color,
                      value: summary.classifications[k] || 0,
                    }))}
                  />
                </div>
                <div>
                  <h3>Material categories</h3>
                  {Object.keys(summary.categories).length ? (
                    <Bars
                      label="Material category counts"
                      rows={Object.entries(summary.categories).map(
                        ([name, value]) => ({ name, value }),
                      )}
                    />
                  ) : (
                    <p>No material entries yet.</p>
                  )}
                </div>
                <div>
                  <h3>OCR confidence</h3>
                  <Bars
                    label="OCR confidence distribution"
                    rows={summary.confidence.map((value, i) => ({
                      name: `${i * 20}–${i * 20 + 20}%`,
                      value,
                    }))}
                  />
                </div>
              </div>
              <h3>Drawings</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>DRAWING</th>
                      <th>STATUS</th>
                      <th>ASBESTOS</th>
                      <th>NON-ASBESTOS</th>
                      <th>REVIEW</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.items.map((d) => (
                      <tr key={d.id}>
                        <td>
                          <button className="link" onClick={() => onOpen(d.id)}>
                            {d.filename}
                          </button>
                        </td>
                        <td>{d.status}</td>
                        <td>{d.classifications.ASBESTOS_CONTAINING}</td>
                        <td>{d.classifications.NON_ASBESTOS}</td>
                        <td>{d.classifications.MANUAL_REVIEW}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!summary.items.length && (
                <p>No drawings are assigned to this project.</p>
              )}
            </>
          )}
        </section>
      )}
    </>
  );
}

type AuditEntry = {
  id: number;
  actor: string;
  action: string;
  entity_id: number;
  payload: string;
  created_at: string;
};
const PAGE = 25;

export function AuditView() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [q, setQ] = useState("");
  const [options, setOptions] = useState<{
    actions: string[];
    actors: string[];
  }>({ actions: [], actors: [] });
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    api<typeof options>("/audit/filters")
      .then(setOptions)
      .catch(() => {});
  }, []);
  useEffect(() => {
    const params = new URLSearchParams({
      limit: String(PAGE),
      offset: String(offset),
    });
    if (action) params.set("action", action);
    if (actor) params.set("actor", actor);
    if (q.trim()) params.set("q", q.trim());
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const response = await fetch("/api/audit?" + params, {
          cache: "no-store",
        });
        if (response.status === 401)
          window.dispatchEvent(new Event("session-expired"));
        if (!response.ok)
          throw Error(`Audit log unavailable (${response.status}).`);
        const body = (await response.json()) as AuditEntry[];
        if (cancelled) return;
        setRows(body);
        setTotal(Number(response.headers.get("X-Total-Count") || body.length));
        setError("");
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [offset, action, actor, q]);
  const pretty = (payload: string) => {
    try {
      return JSON.stringify(JSON.parse(payload), null, 2);
    } catch {
      return payload;
    }
  };
  const when = (v: string) =>
    new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(v) ? v : v + "Z").toLocaleString();
  return (
    <section className="card audit">
      <div className="card-title">
        <h2>Audit log</h2>
        <span>{total} events</span>
      </div>
      <div className="filter-bar" role="search" aria-label="Filter audit log">
        <input
          type="search"
          aria-label="Search audit log"
          placeholder="Search action or details"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
        />
        <select
          aria-label="Filter by action"
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All actions</option>
          {options.actions.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <select
          aria-label="Filter by actor"
          value={actor}
          onChange={(e) => {
            setActor(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All actors</option>
          {options.actors.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>TIME</th>
              <th>ACTOR</th>
              <th>ACTION</th>
              <th>ENTITY</th>
              <th>DETAILS</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{when(r.created_at)}</td>
                <td>{r.actor}</td>
                <td>
                  <code>{r.action}</code>
                </td>
                <td>#{r.entity_id}</td>
                <td>
                  <button
                    className="link"
                    aria-expanded={open === r.id}
                    onClick={() => setOpen(open === r.id ? null : r.id)}
                  >
                    {open === r.id ? "Hide" : "Show"}
                  </button>
                  {open === r.id && <pre>{pretty(r.payload)}</pre>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && !error && <p>No audit events match.</p>}
      <div className="card-title" aria-label="Audit pagination">
        <button
          className="button"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
        >
          Newer
        </button>
        <span>
          {total ? offset + 1 : 0}–{Math.min(total, offset + PAGE)} of {total}
        </span>
        <button
          className="button"
          disabled={offset + PAGE >= total}
          onClick={() => setOffset(offset + PAGE)}
        >
          Older
        </button>
      </div>
    </section>
  );
}
