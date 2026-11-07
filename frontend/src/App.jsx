import { useEffect, useState } from "react";
import { supabase } from "./supabaseClient";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const fmt = (n) =>
  n == null ? "" : Number(n).toLocaleString(undefined, { minimumFractionDigits: 2 });

function toCsv(rows) {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  const esc = (v) => {
    if (v == null) return "";
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\r\n");
}

function AuthForm() {
  const [mode, setMode] = useState("signin"); // signin | signup
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);

  async function submit() {
    setBusy(true);
    setMessage("");
    setFailed(false);
    const { data, error } =
      mode === "signup"
        ? await supabase.auth.signUp({ email, password })
        : await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) {
      setFailed(true);
      setMessage(error.message);
    } else if (mode === "signup" && !data.session) {
      setMessage("Account created. Check your email to confirm it, then sign in.");
    }
  }

  return (
    <section className="card auth">
      <h2>{mode === "signup" ? "Create your account" : "Sign in"}</h2>
      <p className="note-small">
        {mode === "signup"
          ? "New accounts get 5 free pages to try it out."
          : "Sign in to convert your statements."}
      </p>
      <input
        type="email"
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <input
        type="password"
        placeholder="Password (at least 6 characters)"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button className="primary" onClick={submit} disabled={busy || !email || !password}>
        {busy ? "Please wait..." : mode === "signup" ? "Sign up" : "Sign in"}
      </button>
      {message && <p className={failed ? "error" : "ok"}>{message}</p>}
      <p className="note-small">
        {mode === "signup" ? "Already have an account? " : "New here? "}
        <button
          className="linklike"
          onClick={() => {
            setMode(mode === "signup" ? "signin" : "signup");
            setMessage("");
          }}
        >
          {mode === "signup" ? "Sign in" : "Create an account"}
        </button>
      </p>
    </section>
  );
}

export default function App() {
  const [session, setSession] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [credits, setCredits] = useState(null);

  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | loading | done | error
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [hideInternal, setHideInternal] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setAuthReady(true);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    async function loadCredits() {
      const { data, error: err } = await supabase.from("profiles").select("credits").maybeSingle();
      if (!err && data) setCredits(data.credits);
    }
    if (session) loadCredits();
  }, [session]);

  async function signOut() {
    await supabase.auth.signOut();
    setCredits(null);
    setFile(null);
    setResult(null);
    setError("");
    setStatus("idle");
  }
  function pick(f) {
    if (!f) return;
    setFile(f);
    setResult(null);
    setError("");
    setStatus("idle");
  }

  function reset() {
    setFile(null);
    setResult(null);
    setError("");
    setStatus("idle");
  }

  async function convert() {
    if (!file || !session) return;
    setStatus("loading");
    setError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${API}/preview`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}` },
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Something went wrong.");
      setResult(data);
      setCredits(data.credits_left);
      setStatus("done");
    } catch (e) {
      setError(
        e.message === "Failed to fetch"
          ? "Cannot reach the server. Is the backend running?"
          : e.message
      );
      setStatus("error");
    }
  }

  const hasTypes = Boolean(result && result.has_types);
  const rows = result
    ? hasTypes && hideInternal
      ? result.rows.filter((r) => r.Type !== "Internal transfer")
      : result.rows
    : [];

  function download() {
    const blob = new Blob(["\ufeff" + toCsv(rows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = file.name.replace(/\.pdf$/i, "") + "_clean.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  if (!authReady) {
    return <div className="shell" />;
  }

  return (
    <div className="shell">
      <header className="top">
        <div className="logo">StatementFlow</div>
        {session && (
          <div className="userbar">
            <span>{session.user.email}</span>
            <span className="credits">{credits == null ? "..." : `${credits} credits`}</span>
            <button className="ghost" onClick={signOut}>Sign out</button>
          </div>
        )}
      </header>

      <main className="page">
        <section className="hero">
          <h1>Turn bank statement PDFs into clean CSV files</h1>
          <p>Ready to import into QuickBooks, Xero or Excel. No retyping.</p>
          <ol className="steps">
            <li><b>1</b> Upload your PDF</li>
            <li><b>2</b> Check the preview</li>
            <li><b>3</b> Download the CSV</li>
          </ol>
        </section>

        {!session ? (
          <AuthForm />
        ) : (
          <>
            <section className="card">
              <label
                className={`drop ${dragging ? "drag" : ""} ${file ? "has-file" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragging(false);
                  pick(e.dataTransfer.files[0]);
                }}
              >
                <input
                  type="file"
                  accept="application/pdf"
                  hidden
                  onChange={(e) => pick(e.target.files[0])}
                />
                <div className="drop-icon">📄</div>
                <div className="drop-title">
                  {file ? file.name : "Drag a PDF here, or click to browse"}
                </div>
                <div className="drop-hint">
                  {file
                    ? "Click to choose a different file"
                    : "PDF statements only, up to 10 MB. Costs 1 credit per page."}
                </div>
              </label>

              <div className="actions">
                <button className="primary" onClick={convert} disabled={!file || status === "loading"}>
                  {status === "loading" ? "Converting..." : "Convert"}
                </button>
                {file && <button className="ghost" onClick={reset}>Clear</button>}
              </div>

              {status === "loading" && <div className="bar"><div className="bar-fill" /></div>}
              {status === "error" && <p className="error">{error}</p>}
            </section>

            {status === "done" && result && (
              <section className="card">
                <div className="stats">
                  <div><span>Transactions shown</span><b>{rows.length}</b></div>
                  <div>
                    <span>{hasTypes ? "Money in" : "Total credits"}</span>
                    <b>{fmt(result.money_in)}</b>
                  </div>
                  <div>
                    <span>{hasTypes ? "Money out" : "Total debits"}</span>
                    <b>{fmt(result.money_out)}</b>
                  </div>
                  <button className="primary" onClick={download}>Download CSV</button>
                </div>
                <p className="note-small">
                  Used {result.pages} {result.pages === 1 ? "credit" : "credits"} for this statement.
                </p>

                {hasTypes && (
                  <>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={hideInternal}
                        onChange={(e) => setHideInternal(e.target.checked)}
                      />
                      Hide transfers between my own accounts ({result.internal_count} rows)
                    </label>
                    <p className="note-small">
                      Money in and money out leave out transfers between your own accounts, so
                      they show your real activity. Interest is counted as money in.
                    </p>
                  </>
                )}

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Description</th>
                        {hasTypes && <th>Account</th>}
                        {hasTypes && <th>Type</th>}
                        <th>Debit</th>
                        <th>Credit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i}>
                          <td>{r.Date}</td>
                          <td>{r.Description}</td>
                          {hasTypes && <td>{r.Account}</td>}
                          {hasTypes && <td>{r.Type}</td>}
                          <td className="num">{fmt(r.Debit)}</td>
                          <td className="num">{fmt(r.Credit)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </>
        )}

        <p className="note">
          Your PDF is processed in memory and is not stored. Currently supports
          several statement layouts, including OPay wallet statements.
        </p>
      </main>
    </div>
  );
}