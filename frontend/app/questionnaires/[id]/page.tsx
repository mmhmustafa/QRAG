"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API, get, send } from "../../../lib/api";
import { formatError } from "../../../lib/errors";
import { useCustomer } from "../../../components/CustomerContext";
const STATUS_LABELS: Record<string, string> = {
  approved_candidate: "Ready to Approve",
  needs_review: "Check Suggested Answer",
  manual_review: "Needs Manual Input",
  approved: "Approved",
  rejected: "Rejected",
  draft: "Draft",
};
const ROLE_LABELS: Record<string, string> = {
  primary: "Primary",
  supporting: "Supporting",
  complementary: "Complementary",
  conflicting: "Conflicting",
  superseded: "Superseded",
  additional: "Additional",
  unrelated: "Additional",
};
const FILTERS = [
  { key: "approved_candidate", label: "Ready to Approve", chip: "ready-chip" },
  { key: "needs_review", label: "Check Suggested", chip: "check-chip" },
  { key: "manual_review", label: "Needs Manual", chip: "manual-chip" },
  { key: "approved", label: "Approved", chip: "done-chip" },
];
export default function Review({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { customer } = useCustomer();
  const searchParams = useSearchParams();
  const [item, setItem] = useState<any>(),
    [id, setId] = useState(""),
    [query, setQuery] = useState(""),
    [generating, setGenerating] = useState(false),
    [working, setWorking] = useState<number>(),
    [editing, setEditing] = useState<number>(),
    [versions, setVersions] = useState<Record<number, any[]>>({}),
    [historyFor, setHistoryFor] = useState<Record<number, boolean>>({}),
    [notice, setNotice] = useState(""),
    [noticeKind, setNoticeKind] = useState<"success" | "error">("success"),
    [selected, setSelected] = useState<number[]>([]),
    [selectMode, setSelectMode] = useState(false),
    [libraryResults, setLibraryResults] = useState<any[]>([]),
    [statusFilter, setStatusFilter] = useState("all"),
    [focus, setFocus] = useState(false),
    [focusIdx, setFocusIdx] = useState(0),
    [progress, setProgress] = useState<any>(),
    [tracking, setTracking] = useState(false);
  const flash = (message: string, kind: "success" | "error" = "success") => {
    setNotice(message);
    setNoticeKind(kind);
  };
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(
      () => setNotice(""),
      noticeKind === "error" ? 10000 : 6000,
    );
    return () => clearTimeout(timer);
  }, [notice, noticeKind]);
  useEffect(() => {
    // Dropdown menus are <details>; close any open one when clicking elsewhere.
    const close = (e: MouseEvent) => {
      document.querySelectorAll("details.menu[open]").forEach((menu) => {
        if (!menu.contains(e.target as Node)) menu.removeAttribute("open");
      });
    };
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, []);
  const load = (qid: string) =>
    customer &&
    get(`/api/customers/${customer.id}/questionnaires/${qid}`)
      .then(setItem)
      .catch((error) => flash(formatError(error), "error"));
  useEffect(() => {
    if (customer)
      params.then(async (p) => {
        setId(p.id);
        void load(p.id);
        try {
          const running = await get(
            `/api/customers/${customer.id}/questionnaires/${p.id}/generation`,
          );
          if (running.state !== "idle") setProgress(running);
          if (running.state === "running") setTracking(true);
        } catch {}
      });
  }, [params, customer]);
  useEffect(() => {
    if (!tracking || !customer || !id) return;
    let ticks = 0;
    const timer = setInterval(async () => {
      try {
        const p = await get(
          `/api/customers/${customer.id}/questionnaires/${id}/generation`,
        );
        setProgress(p);
        ticks++;
        if (p.state === "running") {
          if (ticks % 5 === 0) void load(id); // refresh answers as they land, without hammering the API
        } else {
          setTracking(false);
          void load(id);
          if (p.state === "failed")
            flash(
              `Generation stopped: ${p.error || "unexpected error"}. Answers generated before the failure were saved.`,
              "error",
            );
          else if (p.summary)
            flash(
              `Generation ${p.state === "cancelled" ? "cancelled" : "completed"} · ${p.summary.processed} of ${p.summary.total} questions processed · ${p.summary.ready} Ready to Approve · ${p.summary.check} Check Suggested Answer · ${p.summary.manual} Need Manual Input${p.summary.failed ? ` · ${p.summary.failed} failed` : ""} · ${formatDuration(p.summary.elapsed_seconds)} total${p.summary.average_seconds ? ` · ${formatDuration(p.summary.average_seconds)} per question` : ""}`,
            );
        }
      } catch {}
    }, 2000);
    return () => clearInterval(timer);
  }, [tracking, customer, id]);
  async function generate(onlyMissing = false, includeApproved = false) {
    if (!customer) return;
    setGenerating(true);
    setNotice("");
    try {
      await send(
        `/api/customers/${customer.id}/questionnaires/${id}/generate`,
        "POST",
        { only_missing: onlyMissing, include_approved: includeApproved },
      );
    } catch (e: any) {
      if (!String(e?.message || "").includes("already running")) {
        flash(formatError(e), "error");
        setGenerating(false);
        return;
      }
    }
    setGenerating(false);
    setTracking(true);
  }
  async function cancelGeneration() {
    if (!customer) return;
    try {
      await send(
        `/api/customers/${customer.id}/questionnaires/${id}/generation/cancel`,
        "POST",
      );
    } catch (e) {
      flash(formatError(e), "error");
    }
  }
  async function save(a: any, status: string) {
    if (!customer) return;
    setWorking(a.id);
    await send(`/api/customers/${customer.id}/answers/${a.id}`, "PATCH", {
      text: a.text,
      status,
    });
    await load(id);
    setWorking(undefined);
    setEditing(undefined);
    flash(status === "approved" ? "Answer approved." : "Answer updated.");
  }
  async function regenerate(a: any) {
    if (!customer) return;
    setWorking(a.id);
    await send(
      `/api/customers/${customer.id}/answers/${a.id}/regenerate`,
      "POST",
    );
    await load(id);
    await history(a.id);
    setWorking(undefined);
    flash("A new answer version was generated.");
  }
  async function history(aid: number) {
    if (!customer) return;
    setVersions((v) => ({ ...v, [aid]: [] }));
    const rows = await get(
      `/api/customers/${customer.id}/answers/${aid}/versions`,
    );
    setVersions((v) => ({ ...v, [aid]: rows }));
  }
  function toggleHistory(aid: number) {
    setHistoryFor((h) => ({ ...h, [aid]: !h[aid] }));
    if (!versions[aid]?.length) void history(aid);
  }
  async function restore(aid: number, version: number) {
    if (!customer) return;
    await send(
      `/api/customers/${customer.id}/answers/${aid}/versions/${version}/restore`,
      "POST",
    );
    await load(id);
    await history(aid);
    flash(`Version ${version} restored as a new draft.`);
  }
  async function bulk(action: string) {
    if (!customer) return;
    await send(`/api/customers/${customer.id}/answers/bulk`, "POST", {
      answer_ids: selected,
      action,
    });
    setSelected([]);
    await load(id);
    flash("Bulk review action completed.");
  }
  async function golden(a: any) {
    if (!customer) return;
    await send(`/api/customers/${customer.id}/answers/${a.id}/golden`, "PATCH", {
      golden: !a.golden,
    });
    await load(id);
    flash(a.golden ? "Golden designation removed." : "Golden Answer created.");
  }
  async function globalAnswer(a: any) {
    if (
      !customer ||
      !confirm(
        "Administrator confirmation: make this answer reusable outside its customer/product scope?",
      )
    )
      return;
    await send(`/api/customers/${customer.id}/answers/${a.id}/global`, "PATCH", {
      global_approved: !a.global_approved,
      admin_confirm: true,
    });
    await load(id);
    flash(
      a.global_approved
        ? "Global approval removed."
        : "Approved Global Answer created by admin.",
    );
  }
  async function reuse(a: any, sourceId: number) {
    if (!customer) return;
    await send(`/api/customers/${customer.id}/answers/${a.id}/reuse`, "POST", {
      source_answer_id: sourceId,
    });
    await load(id);
    flash("Previously approved answer reused.");
  }
  async function searchLibrary() {
    if (!customer) return;
    setLibraryResults(
      await get(
        `/api/customers/${customer.id}/approved-answers/search?q=${encodeURIComponent(query)}&collections=${encodeURIComponent((item.collections || []).join(","))}`,
      ),
    );
  }
  function updateText(answerId: number, text: string) {
    setItem((current: any) => ({
      ...current,
      questions: current.questions.map((question: any) =>
        question.answer?.id === answerId
          ? { ...question, answer: { ...question.answer, text } }
          : question,
      ),
    }));
  }
  useEffect(() => {
    if (!focus || !item) return;
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["TEXTAREA", "INPUT", "SELECT"].includes(target.tagName)) return;
      const pendingList = item.questions.filter(
        (q: any) =>
          q.answer && !["approved", "rejected"].includes(q.answer.status),
      );
      const current = pendingList[Math.min(focusIdx, pendingList.length - 1)];
      if (!current) return;
      if (e.key === "a" || e.key === "A") {
        e.preventDefault();
        void save(current.answer, "approved");
      } else if (e.key === "n" || e.key === "ArrowRight") {
        e.preventDefault();
        setFocusIdx((i) => Math.min(i + 1, pendingList.length - 1));
      } else if (e.key === "p" || e.key === "ArrowLeft") {
        e.preventDefault();
        setFocusIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "e" || e.key === "E") {
        e.preventDefault();
        setEditing(current.answer.id);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focus, item, focusIdx]);
  if (!item)
    return (
      <div className="loading">
        <span className="spinner" />
        Loading review workspace…
      </div>
    );
  const total = item.questions.length,
    answered = item.questions.filter((q: any) => q.answer).length,
    ready = item.questions.filter(
      (q: any) => q.answer?.status === "approved_candidate",
    ).length,
    approved = item.questions.filter(
      (q: any) => q.answer?.status === "approved",
    ).length,
    counts: Record<string, number> = {
      approved_candidate: ready,
      needs_review: item.questions.filter(
        (q: any) => q.answer?.status === "needs_review",
      ).length,
      manual_review: item.questions.filter(
        (q: any) => q.answer?.status === "manual_review",
      ).length,
      approved,
    },
    matchesFilter = (q: any) =>
      statusFilter === "all" ||
      (statusFilter === "unanswered" ? !q.answer : q.answer?.status === statusFilter),
    visible = item.questions.filter(
      (q: any) =>
        matchesFilter(q) &&
        (q.text + " " + (q.answer?.text || ""))
          .toLowerCase()
          .includes(query.toLowerCase()),
    ),
    pending = visible.filter(
      (q: any) =>
        q.answer && !["approved", "rejected"].includes(q.answer.status),
    ),
    focusCard = focus ? pending[Math.min(focusIdx, pending.length - 1)] : null;
  function confirmRegenerate(includeApproved = false) {
    if (includeApproved) {
      if (
        !confirm(
          `Replace ALL ${total} answers, including your ${approved} approved answer${approved !== 1 ? "s" : ""}?\n\nPrevious versions remain available in Answer History.`,
        )
      )
        return;
      void generate(false, true);
      return;
    }
    if (
      approved > 0 &&
      !confirm(
        `Regenerate ${total - approved} answers?\n\nYour ${approved} approved answer${approved !== 1 ? "s" : ""} will be kept unchanged.`,
      )
    )
      return;
    void generate();
  }
  function jumpTo(q: any) {
    if (!matchesFilter(q)) setStatusFilter("all");
    if (focus) {
      const idx = pending.findIndex((x: any) => x.id === q.id);
      if (idx >= 0) {
        setFocusIdx(idx);
        return;
      }
      setFocus(false);
    }
    setTimeout(
      () =>
        document
          .getElementById(`q-card-${q.id}`)
          ?.scrollIntoView({ behavior: "smooth", block: "start" }),
      80,
    );
  }
  function jumpClass(q: any) {
    const live = progress?.question_status?.[q.id];
    if (live === "processing") return "jump-processing";
    if (live === "failed") return "jump-failed";
    if (!q.answer) return "jump-none";
    return (
      {
        approved: "jump-approved",
        approved_candidate: "jump-ready",
        needs_review: "jump-check",
        manual_review: "jump-manual",
      }[q.answer.status as string] || "jump-none"
    );
  }
  return (
    <>
      <div className="review-toolbar">
        <div className="rt-title">
          <div className="eyebrow">
            {customer?.name}
            {item.collections?.length
              ? ` · ${item.collections.join(", ")}`
              : ""}
          </div>
          <strong title={item.name}>{item.name}</strong>
        </div>
        <div className="rt-progress">
          <span className="progress">
            <i style={{ width: `${total ? Math.round((100 * approved) / total) : 0}%` }} />
          </span>
          <span className="label">
            {approved} of {total} approved
          </span>
        </div>
        <input
          className="search rt-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search questions…"
        />
        {answered > 0 && (
          <details className="menu">
            <summary className="button secondary">Export ▾</summary>
            <div className="menu-list">
              <a
                onClick={closeMenu}
                href={`${API}/api/customers/${customer?.id}/questionnaires/${id}/export`}
              >
                Export customer copy
              </a>
              <a
                onClick={closeMenu}
                href={`${API}/api/customers/${customer?.id}/questionnaires/${id}/export-internal`}
              >
                Export with internal evidence
              </a>
            </div>
          </details>
        )}
        <button
          disabled={generating || tracking}
          onClick={() => confirmRegenerate()}
        >
          {generating || tracking
            ? "Generating…"
            : answered
              ? "Regenerate All"
              : "Generate Answers"}
        </button>
      </div>
      {notice && (
        <div className={`toast ${noticeKind === "error" ? "error" : ""}`}>
          <span>{notice}</span>
          <button aria-label="Dismiss" onClick={() => setNotice("")}>
            ✕
          </button>
        </div>
      )}
      {tracking && progress && (
        <div className="card generation-progress">
          <div className="generation-head">
            <div>
              <strong>Generating answers</strong>
              <span className="label">
                {" "}
                · {progress.stage_label || "Preparing questionnaire"}
              </span>
            </div>
            <button className="secondary" onClick={cancelGeneration}>
              Cancel Generation
            </button>
          </div>
          <div className="progress generation-bar">
            <i style={{ width: `${progress.percent || 0}%` }} />
          </div>
          <div className="generation-stats">
            <span>
              <strong>
                {progress.completed} / {progress.total}
              </strong>{" "}
              completed
            </span>
            <span>
              <strong>{progress.remaining}</strong> remaining
            </span>
            <span>
              <strong>{progress.percent || 0}%</strong>
            </span>
            <span>
              <strong>{formatDuration(progress.elapsed_seconds)}</strong>{" "}
              elapsed
            </span>
            {progress.eta_seconds != null && (
              <span>
                <strong>~{formatDuration(progress.eta_seconds)}</strong>{" "}
                remaining
              </span>
            )}
            {progress.failed_count > 0 && (
              <span className="generation-failed">
                <strong>{progress.failed_count}</strong> failed
              </span>
            )}
          </div>
          {progress.current_question && (
            <p className="label">
              Currently processing Q{progress.current_ordinal}: “
              {progress.current_question}”
            </p>
          )}
        </div>
      )}
      {!tracking && progress?.state === "cancelled" && answered < total && (
        <div className="notice warning-notice">
          <strong>
            Generation was cancelled — {answered} of {total} questions have
            answers.
          </strong>{" "}
          <button
            className="mini"
            disabled={generating}
            onClick={() => generate(true)}
          >
            Resume remaining questions
          </button>
        </div>
      )}
      {!answered && !tracking && (
        <div className="card empty">
          <div className="empty-icon">✦</div>
          <h2>{total} questions found</h2>
          <p>
            Review your knowledge and settings, then generate evidence-grounded
            answers.
          </p>
          <button onClick={() => generate()}>Generate Answers</button>
        </div>
      )}
      {answered > 0 && (
        <div className="filter-row">
          <button
            className={`filter-chip ${statusFilter === "all" ? "active" : ""}`}
            onClick={() => setStatusFilter("all")}
          >
            All <strong>{total}</strong>
          </button>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className={`filter-chip ${f.chip} ${statusFilter === f.key ? "active" : ""}`}
              onClick={() =>
                setStatusFilter(statusFilter === f.key ? "all" : f.key)
              }
            >
              {f.label} <strong>{counts[f.key]}</strong>
            </button>
          ))}
          {answered < total && (
            <button
              className={`filter-chip ${statusFilter === "unanswered" ? "active" : ""}`}
              onClick={() =>
                setStatusFilter(
                  statusFilter === "unanswered" ? "all" : "unanswered",
                )
              }
            >
              Unanswered <strong>{total - answered}</strong>
            </button>
          )}
          <span className="grow" />
          {ready > 0 && (
            <button onClick={() => bulk("approve_high")}>
              Approve All Ready ({ready})
            </button>
          )}
          <button
            className="secondary"
            onClick={() => {
              setFocusIdx(0);
              setFocus(!focus);
            }}
          >
            {focus ? "Exit Focus Review" : "Focus Review"}
          </button>
          <details className="menu">
            <summary
              className="button secondary menu-dots"
              aria-label="More actions"
            >
              ⋯
            </summary>
            <div className="menu-list">
              <button
                onClick={(e) => {
                  closeMenu(e);
                  setSelectMode(!selectMode);
                  setSelected([]);
                }}
              >
                {selectMode ? "Exit select mode" : "Select multiple…"}
              </button>
              <button
                onClick={(e) => {
                  closeMenu(e);
                  void searchLibrary();
                }}
              >
                Search approved answers
              </button>
              {approved > 0 && (
                <button
                  onClick={(e) => {
                    closeMenu(e);
                    confirmRegenerate(true);
                  }}
                >
                  Regenerate all incl. approved…
                </button>
              )}
            </div>
          </details>
        </div>
      )}
      {item.questions.length > 5 && answered > 0 && (
        <div className="jump-strip" aria-label="Jump to question">
          {item.questions.map((q: any) => (
            <button
              key={q.id}
              className={`${jumpClass(q)} ${focusCard?.id === q.id ? "jump-current" : ""}`}
              title={`Q${q.ordinal + 1}: ${q.text.slice(0, 90)}`}
              onClick={() => jumpTo(q)}
            >
              {q.ordinal + 1}
            </button>
          ))}
        </div>
      )}
      {libraryResults.length > 0 && (
        <div className="card">
          <div className="rc-head">
            <strong>
              Similar question search · {(item.collections || []).join(", ")}
            </strong>
            <span className="grow" />
            <button className="mini" onClick={() => setLibraryResults([])}>
              Close
            </button>
          </div>
          {libraryResults.slice(0, 8).map((x) => (
            <div className="row" key={x.answer_id}>
              <span>
                <b>
                  {x.golden ? "⭐ " : ""}
                  {x.question}
                </b>
                <br />
                <span className="label">
                  {x.customer} · {(x.collections || []).join(", ")} · {x.answer}
                </span>
              </span>
              <span className="badge approved">{x.match_badge}</span>
            </div>
          ))}
        </div>
      )}
      {selectMode && !focus && (
        <div className="actions bulk-actions">
          <button disabled={!selected.length} onClick={() => bulk("approve")}>
            Approve Selected
          </button>
          <button
            className="secondary"
            disabled={!selected.length}
            onClick={() => bulk("manual")}
          >
            Mark for Manual Input
          </button>
          <button
            className="secondary"
            disabled={!selected.length}
            onClick={() => bulk("regenerate")}
          >
            Regenerate Selected
          </button>
          <span className="label">{selected.length} selected</span>
          <span className="grow" />
          <button
            className="secondary"
            onClick={() => {
              setSelectMode(false);
              setSelected([]);
            }}
          >
            Done
          </button>
        </div>
      )}
      {focus && (
        <div className="focus-head">
          {pending.length ? (
            <>
              <span className="label">
                Reviewing {Math.min(focusIdx, pending.length - 1) + 1} of{" "}
                {pending.length} remaining · <kbd>A</kbd> approve ·{" "}
                <kbd>E</kbd> edit · <kbd>←</kbd>/<kbd>→</kbd> navigate
              </span>
              <div className="actions">
                <button
                  className="secondary"
                  disabled={focusIdx <= 0}
                  onClick={() => setFocusIdx((i) => Math.max(i - 1, 0))}
                >
                  ← Previous
                </button>
                <button
                  className="secondary"
                  disabled={focusIdx >= pending.length - 1}
                  onClick={() =>
                    setFocusIdx((i) => Math.min(i + 1, pending.length - 1))
                  }
                >
                  Next →
                </button>
              </div>
            </>
          ) : (
            <span className="label">
              All answers reviewed — nothing left in the queue. 🎉
            </span>
          )}
        </div>
      )}
      {answered > 0 && !focus && (
        <div className="shown-count label">
          {visible.length} of {total} questions shown
          {statusFilter !== "all" || query ? " (filtered)" : ""}
        </div>
      )}
      {(focus ? (focusCard ? [focusCard] : []) : visible).map((q: any) => (
        <AnswerCard
          key={q.id}
          q={q}
          number={q.ordinal + 1}
          customerId={customer?.id}
          editing={editing === q.answer?.id}
          setEditing={setEditing}
          cancelEdit={() => {
            setEditing(undefined);
            void load(id);
          }}
          updateText={updateText}
          working={working}
          save={save}
          regenerate={regenerate}
          versions={versions[q.answer?.id]}
          historyOpen={!!historyFor[q.answer?.id]}
          toggleHistory={toggleHistory}
          restore={restore}
          selectMode={selectMode}
          selected={selected.includes(q.answer?.id)}
          toggleSelected={(aid: number) =>
            setSelected((current) =>
              current.includes(aid)
                ? current.filter((x) => x !== aid)
                : [...current, aid],
            )
          }
          golden={golden}
          globalAnswer={globalAnswer}
          reuse={reuse}
          liveStatus={progress?.question_status?.[q.id]}
          liveError={progress?.question_errors?.[q.id]}
          showDebug={searchParams.get("debug") === "1"}
        />
      ))}
    </>
  );
}
const LIVE_LABELS: Record<string, string> = {
  queued: "Queued",
  processing: "Processing…",
  cancelled: "Cancelled",
  failed: "Failed",
};
function closeMenu(e: any) {
  e.currentTarget.closest("details")?.removeAttribute("open");
}
function AnswerCard(p: any) {
  const { q } = p,
    a = q.answer;
  if (!a)
    return (
      <article
        id={`q-card-${q.id}`}
        className={`review-card unanswered ${p.liveStatus === "processing" ? "processing-card" : ""}`}
      >
        <div className="rc-body">
          <div className="rc-head">
            <span className="qnum">Q{p.number}</span>
            <span className="grow" />
            <span
              className={`badge ${p.liveStatus === "failed" ? "failed-badge" : p.liveStatus === "processing" ? "processing-badge" : "ready"}`}
            >
              {LIVE_LABELS[p.liveStatus] || "Not generated"}
            </span>
          </div>
          <h2 className="rc-question">{q.text}</h2>
          {p.liveStatus === "failed" && p.liveError && (
            <div className="rc-note failed-note">
              Generation failed: {p.liveError}
            </div>
          )}
        </div>
      </article>
    );
  return (
    <article id={`q-card-${q.id}`} className={`review-card ${a.status}`}>
      <div className="rc-body">
        <div className="rc-head">
          {p.selectMode && (
            <input
              className="review-select"
              type="checkbox"
              checked={p.selected}
              onChange={() => p.toggleSelected(a.id)}
              aria-label="Select answer"
            />
          )}
          <span className="qnum">Q{p.number}</span>
          <span className="grow" />
          {p.liveStatus === "processing" && (
            <span className="badge processing-badge">Processing…</span>
          )}
          {p.liveStatus === "failed" && (
            <span
              className="badge failed-badge"
              title={p.liveError || "Generation failed; previous answer kept"}
            >
              Regeneration failed
            </span>
          )}
          <span className={`badge ${a.status}`}>
            {STATUS_LABELS[a.status] || a.status.replaceAll("_", " ")}
            {a.golden ? " · ⭐ Golden" : ""}
          </span>
        </div>
        <h2 className="rc-question">{q.text}</h2>
        {p.editing ? (
          <textarea
            value={a.text}
            autoFocus
            onChange={(e) => p.updateText(a.id, e.target.value)}
          />
        ) : (
          <div className="rc-answer">{a.text}</div>
        )}
        <div className="rc-note">
          <span>
            {a.classification_reason || "Reviewer verification recommended."}
          </span>
          {a.debug_data?.conflicting_documents?.length > 0 && (
            <span className="conflict-warning">
              ⚠ Contradicting sources:{" "}
              {a.debug_data.conflicting_documents.join(", ")}
            </span>
          )}
        </div>
        <div className="rc-actions">
          {p.editing ? (
            <>
              <button
                disabled={p.working === a.id}
                onClick={() => p.save(a, "draft")}
              >
                Save Edit
              </button>
              <button className="secondary" onClick={p.cancelEdit}>
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                disabled={p.working === a.id}
                onClick={() => p.save(a, "approved")}
              >
                Approve
              </button>
              <button className="secondary" onClick={() => p.setEditing(a.id)}>
                Edit
              </button>
              <details className="menu">
                <summary
                  className="button secondary menu-dots"
                  aria-label="More actions"
                >
                  ⋯
                </summary>
                <div className="menu-list">
                  <button
                    disabled={p.working === a.id}
                    onClick={(e) => {
                      closeMenu(e);
                      p.save(a, "rejected");
                    }}
                  >
                    Reject
                  </button>
                  <button
                    disabled={p.working === a.id}
                    onClick={(e) => {
                      closeMenu(e);
                      p.regenerate(a);
                    }}
                  >
                    {p.working === a.id ? "Regenerating…" : "Regenerate"}
                  </button>
                  <button
                    onClick={(e) => {
                      closeMenu(e);
                      p.golden(a);
                    }}
                  >
                    {a.golden ? "Remove Golden" : "Mark as Golden"}
                  </button>
                  {a.status === "approved" && (
                    <button
                      onClick={(e) => {
                        closeMenu(e);
                        p.globalAnswer(a);
                      }}
                    >
                      {a.global_approved
                        ? "Remove Global Approval"
                        : "Admin: Approve Global Answer"}
                    </button>
                  )}
                  <button
                    onClick={(e) => {
                      closeMenu(e);
                      p.toggleHistory(a.id);
                    }}
                  >
                    {p.historyOpen ? "Hide Answer History" : "Answer History"}
                  </button>
                </div>
              </details>
            </>
          )}
        </div>
        {a.sources?.length > 0 ? (
          <details className="evidence-details">
            <summary>
              <span className="chev">▸</span>Evidence · {a.sources.length}{" "}
              source{a.sources.length !== 1 ? "s" : ""}
              {a.debug_data?.evidence_analysis?.primary_document
                ? ` · primary: ${a.debug_data.evidence_analysis.primary_document}`
                : ""}
            </summary>
            <div className="evidence-body">
              <div className="quality-breakdown">
                <div>
                  <span>Evidence Strength</span>
                  <strong>
                    {strengthInfo(a.confidence).label} ·{" "}
                    {Math.round(a.confidence * 100)}%
                  </strong>
                </div>
                <div>
                  <span>Retrieval Match</span>
                  <strong>
                    {Math.round(
                      (a.debug_data?.retrieval_quality ?? a.confidence) * 100,
                    )}
                    %
                  </strong>
                </div>
                <div>
                  <span>Source Consistency</span>
                  <strong>
                    {Math.round((a.debug_data?.evidence_consistency ?? 0) * 100)}
                    %
                  </strong>
                </div>
              </div>
              {a.debug_data?.superseded_documents?.length > 0 && (
                <p className="label">
                  Superseded by higher-authority documentation:{" "}
                  {a.debug_data.superseded_documents.join(", ")}
                </p>
              )}
              <div className="evidence-list">
                {a.sources.map((s: any) => (
                  <details className="evidence-item" key={s.chunk_id}>
                    <summary>
                      <div>
                        <strong>{s.document}</strong>
                        <span>
                          {s.category} · Page {s.page_number || "Unknown"} ·{" "}
                          {(s.score * 100).toFixed(1)}% match
                        </span>
                      </div>
                      {s.role && (
                        <span className={`role-badge role-${s.role}`}>
                          {ROLE_LABELS[s.role] || s.role}
                        </span>
                      )}
                    </summary>
                    <p>{s.text_preview}</p>
                    <Link
                      className="mini"
                      target="_blank"
                      href={`/documents/${s.document_id}?chunk=${s.chunk_id}`}
                    >
                      Open Source
                    </Link>
                  </details>
                ))}
              </div>
            </div>
          </details>
        ) : (
          <div className="rc-note">No supporting evidence found.</div>
        )}
        {a.suggestions?.length > 0 && (
          <details className="evidence-details suggestion-details">
            <summary>
              <span className="chev">▸</span>⭐ Previously approved answer
              found ({a.suggestions.length})
            </summary>
            <div className="evidence-body">
              {a.suggestions.map((s: any) => (
                <div className="suggestion" key={s.answer_id}>
                  <strong>
                    {s.golden ? "⭐ Golden Answer" : "Approved Answer"} ·{" "}
                    {Math.round(s.similarity * 100)}%
                  </strong>
                  <span>
                    {s.match_badge} · {s.customer} ·{" "}
                    {(s.collections || []).join(", ") || "No collections"} ·{" "}
                    {s.category}
                  </span>
                  <span>
                    Approved{" "}
                    {s.approved_at
                      ? new Date(s.approved_at).toLocaleDateString()
                      : "—"}{" "}
                    by {s.reviewer} · Evidence: {s.evidence_status}
                  </span>
                  <p>{s.answer}</p>
                  <button
                    className="mini"
                    disabled={!s.evidence_current}
                    onClick={() => p.reuse(a, s.answer_id)}
                  >
                    {s.evidence_current
                      ? "Reuse Previous"
                      : "Needs Review – Evidence Changed"}
                  </button>
                </div>
              ))}
            </div>
          </details>
        )}
        {p.historyOpen && (
          <div className="history-section">
            <div className="panel-label">ANSWER HISTORY</div>
            {p.versions?.length ? (
              p.versions.map((v: any) => (
                <div className="version-row" key={v.id}>
                  <div>
                    <strong>Version {v.version}</strong>
                    <span>
                      {new Date(v.created_at).toLocaleString()} ·{" "}
                      {strengthInfo(v.confidence).label} evidence
                    </span>
                  </div>
                  <p>{v.text}</p>
                  <button
                    className="mini secondary"
                    onClick={() => p.restore(a.id, v.version)}
                  >
                    Restore
                  </button>
                </div>
              ))
            ) : (
              <p className="label">Loading versions…</p>
            )}
          </div>
        )}
        {p.showDebug && (
          <details className="admin-debug">
            <summary>Administrator: Retrieval & LLM Diagnostics</summary>
            <div className="debug-grid">
              <div>
                <strong>Prompt sent to LLM</strong>
                <pre>{a.debug_data?.prompt || "Not available"}</pre>
              </div>
              <div>
                <strong>LLM response</strong>
                <pre>{a.debug_data?.llm_response || a.text}</pre>
              </div>
              <div>
                <strong>Execution</strong>
                <p>
                  {a.debug_data?.execution_time_ms ?? "—"} ms · Retrieval cache{" "}
                  {a.debug_data?.cache_hit ? "hit" : "miss"}
                </p>
              </div>
              <div>
                <strong>Retrieved chunks</strong>
                {a.debug_data?.retrieved_chunks?.map((x: any) => (
                  <p key={x.chunk_id}>
                    #{x.chunk_id} · {(x.score * 100).toFixed(1)}% · {x.document}
                  </p>
                ))}
              </div>
            </div>
          </details>
        )}
      </div>
    </article>
  );
}
function formatDuration(seconds: number) {
  if (seconds == null || !isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds * 10) / 10}s`;
  const minutes = Math.floor(seconds / 60),
    rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${rest}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
function strengthInfo(score: number) {
  // Evidence framing, not answer-confidence: the score measures documentation coverage.
  // Buckets track the backend's status thresholds: >=0.7 is the auto-approve candidate boundary.
  if (score >= 0.7) return { label: "Strong", className: "high" };
  if (score >= 0.45) return { label: "Good", className: "medium" };
  if (score >= 0.25) return { label: "Limited", className: "low" };
  return { label: "Minimal", className: "very-low" };
}
