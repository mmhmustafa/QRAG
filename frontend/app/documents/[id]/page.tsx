"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { API, get } from "../../../lib/api";
import { formatError } from "../../../lib/errors";
import { useCustomer } from "../../../components/CustomerContext";
export default function DocumentViewer({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { customer } = useCustomer();
  const search = useSearchParams();
  const router = useRouter();
  const [doc, setDoc] = useState<any>(),
    [id, setId] = useState(""),
    [query, setQuery] = useState(""),
    [zoom, setZoom] = useState(100),[error,setError]=useState("");
  const chunkId = search.get("chunk");
  useEffect(() => {
    if (customer)
      params.then((p) => {
        setId(p.id);
        setDoc(undefined);
        get(
          `/api/customers/${customer.id}/documents/${p.id}/preview${chunkId ? `?chunk_id=${chunkId}` : ""}`,
        ).then(setDoc).catch(value=>{
          // Document belongs to another customer after a workspace switch; go to the active customer's knowledge base.
          if(String((value as any)?.message||"").includes("API endpoint not found"))return void router.replace("/knowledge");
          setError(formatError(value));
        });
      });
  }, [customer, params, chunkId]);
  const displayed = useMemo(() => {
    if (!doc) return "";
    const needle = query || doc.chunk?.content;
    if (!needle) return doc.text;
    const position = doc.text
      .toLowerCase()
      .indexOf(needle.toLowerCase().slice(0, 120));
    if (position < 0) return doc.text;
    return (
      doc.text.slice(0, position) +
      "<mark>" +
      doc.text.slice(position, position + needle.length) +
      "</mark>" +
      doc.text.slice(position + needle.length)
    );
  }, [doc, query]);
  if(error)return <><div className="notice error-notice">{error}</div><Link className="button secondary" href="/knowledge">← Back to Knowledge base</Link></>;
  if (!doc)
    return (
      <div className="loading">
        <span className="spinner" />
        Opening source…
      </div>
    );
  const download = `${API}${doc.download_url}`;
  return (
    <>
      <div className="pagehead">
        <div>
          <div className="eyebrow">
            <Link href="/knowledge">Knowledge base</Link> · Source Viewer ·{" "}
            {doc.category}
          </div>
          <h1>{doc.name}</h1>
          <p className="sub">
            Chunk #{doc.chunk?.id || "—"} · Page{" "}
            {doc.chunk?.page_number || "Unknown"}
          </p>
        </div>
        <div className="actions">
          <Link className="button secondary" href="/knowledge">
            ← Back to Knowledge base
          </Link>
          <a className="button secondary" href={download}>
            Download original
          </a>
        </div>
      </div>
      <div className="viewer-toolbar">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search within document…"
        />
        <button
          className="secondary"
          onClick={() => setZoom(Math.max(50, zoom - 10))}
        >
          −
        </button>
        <span>{zoom}%</span>
        <button
          className="secondary"
          onClick={() => setZoom(Math.min(180, zoom + 10))}
        >
          +
        </button>
      </div>
      <div className="source-viewer">
        {doc.type === "pdf" ? (
          <iframe
            title={doc.name}
            src={`${download}#page=${doc.chunk?.page_number || 1}&zoom=${zoom}`}
          />
        ) : (
          <div
            className="text-preview"
            style={{ fontSize: `${zoom}%` }}
            dangerouslySetInnerHTML={{ __html: escapeExceptMark(displayed) }}
          />
        )}
        <aside>
          <div className="panel-label">RETRIEVED CHUNK</div>
          <p>{doc.chunk?.content || "No chunk selected."}</p>
          <dl>
            <dt>Document</dt>
            <dd>{doc.name}</dd>
            <dt>Category</dt>
            <dd>{doc.category}</dd>
            <dt>Page</dt>
            <dd>{doc.chunk?.page_number || "Unknown"}</dd>
            <dt>Chunk ID</dt>
            <dd>{doc.chunk?.id || "—"}</dd>
          </dl>
        </aside>
      </div>
    </>
  );
}
function escapeExceptMark(value: string) {
  return value
    .split(/(<\/?mark>)/)
    .map((part) =>
      part === "<mark>" || part === "</mark>"
        ? part
        : part
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;"),
    )
    .join("");
}
