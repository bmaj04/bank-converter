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

  async function handleFile(f) {
    if (!f) return;
    setFile(f);
    setResult(null);
    setError("");
    setStatus("loading");

    const form = new FormData();
    form.append("file", f);
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
    <main className="page">
      <h1>Bank Statement to CSV</h1>
      <p className="sub">Drop a PDF statement and get a clean CSV for QuickBooks, Xero or Excel.</p>

      <label
        className={`drop ${dragging ? "drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFile(e.dataTransfer.files[0]);
        }}
      >
        <input
          type="file"
          accept="application/pdf"
          hidden
          onChange={(e) => handleFile(e.target.files[0])}
        />
        {file ? file.name : "Drag a PDF here, or click to choose one"}
      </label>

      {status === "loading" && (
        <div className="bar"><div className="bar-fill" /></div>
      )}
      {status === "error" && <p className="error">{error}</p>}

      {status === "done" && result && (
        <>
          <div className="summary">
            <span>{result.count} transactions</span>
            <span>Debits: {fmt(result.total_debits)}</span>
            <span>Credits: {fmt(result.total_credits)}</span>
            <button onClick={download}>Download CSV</button>
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
        </>
      )}
    </main>
  );
}