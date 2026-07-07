"use client";
import { DragEvent, useEffect, useRef, useState } from "react";
import { API, get, send, upload } from "../../lib/api";
import { formatError } from "../../lib/errors";
import { useCustomer } from "../../components/CustomerContext";
const categories = [
  "Company",
  "Products",
  "Security",
  "Compliance",
  "Legal",
  "Support",
  "Operations",
  "Previous Questionnaires",
];
const allowed = ["pdf", "docx", "xlsx", "csv", "txt"],
  maxBytes = 25 * 1024 * 1024;
type Status =
  | "ready"
  | "uploading"
  | "parsing"
  | "chunking"
  | "embedding"
  | "completed"
  | "failed";
type Queued = {
  id: string;
  file: File;
  status: Status;
  error?: string;
  progress: number;
};
type Collection={name:string;document_count:number;categories:string[]};
const size = (n: number) =>
  n < 1024
    ? `${n} B`
    : n < 1048576
      ? `${(n / 1024).toFixed(1)} KB`
      : `${(n / 1048576).toFixed(1)} MB`;
const errorText = formatError;
export default function Knowledge() {
  const { customer } = useCustomer();
  const [docs, setDocs] = useState<any[]>([]),
    [indexConfig, setIndexConfig] = useState<any>(),
    [category, setCategory] = useState("Company"),
    [collectionsInput,setCollectionsInput]=useState("General"),
    [allCollections,setAllCollections]=useState<Collection[]>([]),[testCollections,setTestCollections]=useState<string[]>([]),
    [loadError,setLoadError]=useState(""),
    [queue, setQueue] = useState<Queued[]>([]),
    [dragging, setDragging] = useState(false),
    [uploading, setUploading] = useState(false),
    [query, setQuery] = useState(""),
    [reindexing, setReindexing] = useState(false),
    [reindexResult, setReindexResult] = useState(""),
    [testQuestion, setTestQuestion] = useState(
      "Where are your support operations located?",
    ),
    [retrieving, setRetrieving] = useState(false),
    [retrieval, setRetrieval] = useState<any>();
  const picker = useRef<HTMLInputElement>(null),
    load = () =>
      customer &&
      Promise.all([
        get(`/api/customers/${customer.id}/documents`),
        get(`/api/customers/${customer.id}/documents/index-config`),
        get(`/api/customers/${customer.id}/collections`),
      ]).then(([documents, config, collections]:[any[],any,Collection[]]) => {
        setDocs(documents);
        setIndexConfig(config);
        setAllCollections(collections);
        const saved=(localStorage.getItem(`testCollections:${customer.id}`)||"").split(",").filter(Boolean).filter(name=>collections.some(x=>x.name===name));
        setTestCollections(saved.length?saved:collections.map(x=>x.name));
        setLoadError("");
      }).catch(error=>{setLoadError(errorText(error));setDocs([]);setAllCollections([]);setTestCollections([])});
  useEffect(() => {
    setDocs([]);
    setIndexConfig(undefined);
    setQueue([]);
    setRetrieval(undefined);
    setAllCollections([]);setTestCollections([]);
    setReindexResult("");
    setLoadError("");
    void load();
  }, [customer]);
  function addFiles(files: File[]) {
    const existing = new Set(
      queue
        .filter((x) => x.status !== "completed")
        .map((x) => `${x.file.name}:${x.file.size}:${x.file.lastModified}`),
    );
    const added = files
      .filter((f) => !existing.has(`${f.name}:${f.size}:${f.lastModified}`))
      .map((file) => {
        const ext = file.name.split(".").pop()?.toLowerCase() || "";
        const error = !allowed.includes(ext)
          ? "Unsupported type. Use PDF, DOCX, XLSX, CSV, or TXT."
          : file.size > maxBytes
            ? "File exceeds the 25 MB maximum."
            : undefined;
        return {
          id: crypto.randomUUID(),
          file,
          status: error ? "failed" : "ready",
          error,
          progress: 0,
        } as Queued;
      });
    setQueue((current) => [...current, ...added]);
  }
  async function uploadAll() {
    if (!customer) return;
    setUploading(true);
    for (const item of queue.filter((x) => x.status === "ready")) {
      const stage = (status: Status, progress: number) =>
        setQueue((q) =>
          q.map((x) => (x.id === item.id ? { ...x, status, progress } : x)),
        );
      stage("uploading", 15);
      const timers = [
        setTimeout(() => stage("parsing", 35), 350),
        setTimeout(() => stage("chunking", 55), 850),
        setTimeout(() => stage("embedding", 75), 1350),
      ];
      try {
        await upload(`/api/customers/${customer.id}/documents`, item.file, {
          category,collections:collectionsInput,
        });
        timers.forEach(clearTimeout);
        stage("completed", 100);
      } catch (e) {
        timers.forEach(clearTimeout);
        setQueue((q) =>
          q.map((x) =>
            x.id === item.id
              ? { ...x, status: "failed", error: errorText(e) }
              : x,
          ),
        );
      }
    }
    setUploading(false);
    void load();
  }
  async function action(id: number, type: string) {
    if (!customer) return;
    if (
      type === "delete" &&
      !confirm("Delete this document, chunks, embeddings, and search records?")
    )
      return;
    await send(
      `/api/customers/${customer.id}/documents/${id}${type === "reindex" ? "/reindex" : ""}`,
      type === "delete" ? "DELETE" : "POST",
    );
    void load();
  }
  async function edit(d: any) {
    if (!customer) return;
    const name = prompt("Document display name", d.name);
    if (!name) return;
    const next = prompt(`Category: ${categories.join(", ")}`, d.category);
    if (!next || !categories.includes(next)) return;
    const tags = prompt(
      "Knowledge Collections (comma-separated)",
      (d.collections || []).join(", "),
    );
    if (tags === null) return;
    await send(`/api/customers/${customer.id}/documents/${d.id}`, "PATCH", {
      name,
      category: next,
      collections: tags.split(",").map((x) => x.trim()).filter(Boolean),
    });
    void load();
  }
  async function replace(d: any, e: any) {
    const file = e.target.files?.[0];
    if (!file || !customer) return;
    await upload(
      `/api/customers/${customer.id}/documents/${d.id}/replace`,
      file,
    );
    void load();
  }
  async function reindexAll() {
    if (!customer) return;
    setReindexing(true);
    setReindexResult("");
    try {
      const r = await send(
        `/api/customers/${customer.id}/documents/reindex-all`,
        "POST",
      );
      setReindexResult(
        `${r.documents - r.results.filter((x: any) => !x.ok).length} documents indexed with ${r.embedding_provider} / ${r.embedding_model} · ${r.vector_records} vector records · ${r.results.filter((x: any) => !x.ok).length} failed`,
      );
      void load();
    } catch (e) {
      setReindexResult(`Re-index failed: ${errorText(e)}`);
    } finally {
      setReindexing(false);
    }
  }
  function toggleTestCollection(name: string) {
    if (!customer) return;
    setTestCollections((current) => {
      const next = current.includes(name)
        ? current.filter((x) => x !== name)
        : [...current, name];
      localStorage.setItem(`testCollections:${customer.id}`, next.join(","));
      return next;
    });
    setRetrieval(undefined);
  }
  async function testRetrieval() {
    if (!customer || !testQuestion.trim()) return;
    if(!testCollections.length){setRetrieval({error:"Select at least one Knowledge Collection to search.",results:[]});return}
    setRetrieving(true);
    try {
      setRetrieval(
        await send(`/api/customers/${customer.id}/retrieval/test`, "POST", {
          customer_id:customer.id,question:testQuestion,collections:testCollections,
        }),
      );
    } catch (e) {
      setRetrieval({ error: errorText(e), results: [] });
    } finally {
      setRetrieving(false);
    }
  }
  const success = queue.filter((x) => x.status === "completed").length,
    failed = queue.filter((x) => x.status === "failed").length,
    ready = queue.filter((x) => x.status === "ready").length;
  const visible = docs.filter((d) =>
    (d.name + " " + d.category).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <div className="pagehead">
        <div>
          <div className="eyebrow">
            {customer?.name || "No customer selected"}
          </div>
          <h1>Knowledge base</h1>
          <p className="sub">
            Manage the approved evidence used for questionnaire answers.
          </p>
        </div>
        <div className="actions">
          <button
            className="secondary"
            disabled={reindexing || !docs.length}
            onClick={reindexAll}
          >
            {reindexing ? "Re-indexing all…" : "Re-index all documents"}
          </button>
          <button onClick={() => picker.current?.click()}>Add documents</button>
        </div>
      </div>
      {loadError&&<div className="notice error-notice">{formatError(loadError)}</div>}
      {indexConfig && (
        <div
          className={`index-config ${indexConfig.documents_requiring_reindex ? "warning" : "ok"}`}
        >
          <div>
            <strong>Active customer: {indexConfig.customer_name}</strong>
            <span>Indexing provider: {indexConfig.embedding_provider}</span>
            <span>Model: {indexConfig.embedding_model}</span>
            <span>
              Source:{" "}
              {indexConfig.settings_source === "customer_override"
                ? "Customer Override"
                : "Global Default"}
            </span>
            <span>Base URL: {indexConfig.base_url}</span>
          </div>
          {indexConfig.documents_requiring_reindex > 0 && (
            <strong>
              {indexConfig.documents_requiring_reindex} documents require
              re-indexing
            </strong>
          )}
        </div>
      )}
      {reindexResult && (
        <div
          className={`notice ${reindexResult.startsWith("Re-index failed") ? "error-notice" : "success-notice"}`}
        >
          {formatError(reindexResult)}
        </div>
      )}
      <div className="card">
        <div className="formgrid">
          <label>Knowledge Collections (comma-separated)
            <input value={collectionsInput} onChange={e=>setCollectionsInput(e.target.value)} placeholder="Product Alpha, Security"/>
            {allCollections.length>0&&<span className="provider-help">Existing: {allCollections.map(x=><button key={x.name} type="button" className="chip" onClick={()=>{const current=collectionsInput.split(",").map(v=>v.trim()).filter(Boolean);if(!current.includes(x.name))setCollectionsInput([...current,x.name].join(", "))}}>{x.name}</button>)}</span>}
          </label>
          <label>
            Category for all selected files
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {categories.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
        </div>
        <div
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e: DragEvent<HTMLDivElement>) => {
            e.preventDefault();
            setDragging(false);
            addFiles(Array.from(e.dataTransfer.files));
          }}
          onClick={() => picker.current?.click()}
        >
          <div className="upload-icon">⇧</div>
          <h2>Drop documents here or choose files</h2>
          <p className="label">
            PDF, DOCX, XLSX, CSV, TXT · Maximum 25 MB per file
          </p>
          <input
            ref={picker}
            hidden
            multiple
            type="file"
            accept=".pdf,.docx,.xlsx,.csv,.txt"
            onChange={(e) => {
              addFiles(Array.from(e.target.files || []));
              e.target.value = "";
            }}
          />
        </div>
        {queue.length > 0 && (
          <div className="uploadqueue">
            <div className="queue-summary">
              <strong>{queue.length} selected</strong>
              <span>
                {success > 0 &&
                  `${success} file${success === 1 ? "" : "s"} uploaded successfully`}
                {success > 0 && failed > 0 ? " · " : ""}
                {failed > 0 &&
                  `${failed} file${failed === 1 ? "" : "s"} failed`}
              </span>
            </div>
            {queue.map((x) => (
              <div className="queue-file" key={x.id}>
                <div>
                  <strong>{x.file.name}</strong>
                  <div className="label">
                    {size(x.file.size)} · {x.file.type || "Unknown type"}
                  </div>
                  {x.error && <div className="file-error">{formatError(x.error)}</div>}
                </div>
                <div className="progress">
                  <i style={{ width: `${x.progress}%` }} />
                </div>
                <span className={`badge ${x.status}`}>{x.status}</span>
                {![
                  "uploading",
                  "parsing",
                  "chunking",
                  "embedding",
                  "completed",
                ].includes(x.status) && (
                  <button
                    className="mini danger"
                    onClick={() =>
                      setQueue((q) => q.filter((y) => y.id !== x.id))
                    }
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
            <div className="actions">
              <button
                disabled={!ready || uploading || !customer}
                onClick={uploadAll}
              >
                {uploading
                  ? "Processing files…"
                  : `Upload ${ready} file${ready === 1 ? "" : "s"}`}
              </button>
              <button
                className="secondary"
                disabled={uploading}
                onClick={() => setQueue([])}
              >
                Clear list
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="toolbar">
        <input
          className="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search documents or categories…"
        />
        <span className="label">{visible.length} documents</span>
      </div>
      {visible.length ? (
        <div className="card data-table">
          <div className="data-row document-row data-head">
            <span>Document</span>
            <span>Category</span>
            <span>Size</span>
            <span>Uploaded</span>
            <span>Index</span>
            <span>Actions</span>
          </div>
          {visible.map((d) => (
            <div className="document-record" key={d.id}>
              <div className="data-row document-row">
                <div>
                  <strong>{d.name}</strong>
                  <div className="label">
                    {d.chunk_count} chunks
                    {d.collections?.length ? ` · ${d.collections.join(", ")}` : ""}
                  </div>
                </div>
                <span>{d.category}</span>
                <span>{size(d.size_bytes)}</span>
                <span className="label">
                  {new Date(d.created_at).toLocaleDateString()}
                </span>
                <span
                  className={`badge ${d.status === "indexed" ? "success" : d.status === "failed" ? "failed" : "uploading"}`}
                >
                  {d.status}
                </span>
                <div className="actions">
                  <a
                    className="mini"
                    href={`${API}/api/customers/${customer?.id}/documents/${d.id}/download`}
                  >
                    Download
                  </a>
                  <button
                    className="mini"
                    onClick={() => action(d.id, "reindex")}
                  >
                    Re-index
                  </button>
                  <button className="mini" onClick={() => edit(d)}>
                    Rename
                  </button>
                  <button
                    className="mini danger"
                    onClick={() => action(d.id, "delete")}
                  >
                    Delete
                  </button>
                </div>
              </div>
              <details className="diagnostics">
                <summary>Index diagnostics</summary>
                <div className="diagnostic-grid">
                  <Metric
                    label="Extracted characters"
                    value={d.extracted_text_length}
                  />
                  <Metric label="Chunks" value={d.chunk_count} />
                  <Metric label="Embeddings" value={d.embedding_count} />
                  <Metric label="Vector records" value={d.vector_count} />
                  <Metric
                    label="Embedding provider"
                    value={d.embedding_provider}
                  />
                  <Metric label="Embedding model" value={d.embedding_model} />
                  <Metric label="Vector dimension" value={d.embedding_dimension || "Re-index required"} />
                  <Metric
                    label="Settings source"
                    value={
                      d.settings_source === "customer_override"
                        ? "Customer Override"
                        : "Global Default"
                    }
                  />
                  <Metric
                    label="Last indexed"
                    value={
                      d.last_indexed_at
                        ? new Date(d.last_indexed_at).toLocaleString()
                        : "Never"
                    }
                  />
                  <Metric label="Index status" value={d.status} />
                </div>
                {d.error_message && (
                  <div className="file-error">{formatError(d.error_message)}</div>
                )}
              </details>
            </div>
          ))}
        </div>
      ) : (
        <div className="card empty">
          <div className="empty-icon">▤</div>
          <h2>No documents yet</h2>
          <p>
            Upload approved company documents to ground questionnaire answers.
          </p>
          <button onClick={() => picker.current?.click()}>
            Upload knowledge documents
          </button>
        </div>
      )}
      <section className="settings-section retrieval-tool">
        <div className="settings-title">
          <span>⌕</span>
          <div>
            <h2>Test Retrieval</h2>
            <p className="label">
              Inspect the chunks vector search finds before any LLM is called.
            </p>
          </div>
        </div>
        <div className="card">
          {allCollections.length===0?<div className="notice warning-notice"><strong>No Knowledge Collections exist for this customer yet.</strong><br/>Upload documents with collections assigned before testing retrieval.</div>:<div className="collection-picker"><span className="label">Search collections</span><div className="chip-row">{allCollections.map(x=><button key={x.name} type="button" className={`chip ${testCollections.includes(x.name)?"chip-on":""}`} onClick={()=>toggleTestCollection(x.name)}>{x.name} ({x.document_count})</button>)}</div></div>}
          <div className="retrieval-input">
            <input
              value={testQuestion}
              onChange={(e) => setTestQuestion(e.target.value)}
              placeholder="Enter a question…"
            />
            <button disabled={retrieving||!testCollections.length||!testQuestion.trim()} onClick={testRetrieval}>
              {retrieving ? "Searching vectors…" : "Test retrieval"}
            </button>
          </div>
          {retrieval?.error && (
            <div className="file-error">{formatError(retrieval.error)}</div>
          )}
          {retrieval && !retrieval.error && (
            <p className="label">
              {retrieval.count} chunks retrieved in {retrieval.latency_ms} ms
            </p>
          )}
          {retrieval?.results?.map((r: any) => (
            <div className="retrieval-result" key={r.chunk_id}>
              <div>
                <strong>{r.document}</strong>
                <span className="badge">
                  {(r.similarity_score * 100).toFixed(1)}%
                </span>
              </div>
              <p>{r.text}</p>
              <div className="label">
                Chunk #{r.chunk_id} · {r.metadata.category} ·{" "}
                {r.metadata.embedding_provider} / {r.metadata.embedding_model}
              </div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
function Metric({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value ?? 0}</strong>
    </div>
  );
}
