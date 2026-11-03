import { useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";
const fmt = (n) =>
  n == null ? "" : Number(n).toLocaleString(undefined, { minimumFractionDigits: 2 });

export default function App() {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | loading | done | error
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [dragging, setDragging] = useState(false);

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
    if (!file) return;
    setStatus("loading");
    setError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${API}/preview`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Something went wrong.");
      setResult(data);
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

  async function download() {
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${API}/convert`, { method: "POST", body: form });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Download failed.");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = file.name.replace(/\.pdf$/i, "") + "_clean.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
      setStatus("error");
    }
  }

  return (
    <div className="shell">
      <header className="top">
        <div className="logo">StatementFlow</div>
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
              {file ? "Click to choose a different file" : "PDF statements only, up to 10 MB"}
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
              <div><span>Transactions</span><b>{result.count}</b></div>
              <div><span>Total debits</span><b>{fmt(result.total_debits)}</b></div>
              <div><span>Total credits</span><b>{fmt(result.total_credits)}</b></div>
              <button className="primary" onClick={download}>Download CSV</button>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Date</th><th>Description</th><th>Debit</th><th>Credit</th></tr>
                </thead>
                <tbody>
                  {result.rows.map((r, i) => (
                    <tr key={i}>
                      <td>{r.Date}</td>
                      <td>{r.Description}</td>
                      <td className="num">{fmt(r.Debit)}</td>
                      <td className="num">{fmt(r.Credit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <p className="note">
          Your PDF is processed in memory and is not stored. Currently supports
          statements with columns for date, year, amount, description and type.
        </p>
      </main>
    </div>
  );
}