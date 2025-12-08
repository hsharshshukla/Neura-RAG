// src/console/pages/BulkUpload.jsx
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import secureAxios from "../../utils/secureAxios"; // ← reuse your resolver

// Derive API base the same way everywhere
const API_BASE = secureAxios?.defaults?.baseURL || "/api/v1";

function prettyBytes(n) {
  if (n == null) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let u = 0, v = n;
  while (v >= 1024 && u < units.length - 1) { v /= 1024; u++; }
  return `${v.toFixed(1)} ${units[u]}`;
}

export default function BulkUpload() {
  const [files, setFiles] = useState([]);
  const [zipFile, setZipFile] = useState(null);
  const [visibility, setVisibility] = useState("private"); // "private" | "global"
  const [namespace, setNamespace] = useState("");
  const [ownerId, setOwnerId] = useState(""); // admins may upload for a user
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null);

  const dropRef = useRef(null);

  const onDrop = useCallback((ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const items = [...ev.dataTransfer.files];
    setFiles((prev) => [...prev, ...items]);
  }, []);

  const onDragOver = useCallback((ev) => {
    ev.preventDefault();
    ev.stopPropagation();
  }, []);

  useEffect(() => {
    const node = dropRef.current;
    if (!node) return;
    node.addEventListener("dragover", onDragOver);
    node.addEventListener("drop", onDrop);
    return () => {
      node.removeEventListener("dragover", onDragOver);
      node.removeEventListener("drop", onDrop);
    };
  }, [onDragOver, onDrop]);

  const totalSize = useMemo(() => files.reduce((s, f) => s + (f.size || 0), 0), [files]);

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const submit = async () => {
    if (!files.length && !zipFile) {
      alert("Add some files or a ZIP to upload");
      return;
    }
    setSubmitting(true);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      if (zipFile) fd.append("zip_file", zipFile);
      fd.append("visibility", visibility);
      if (namespace.trim()) fd.append("namespace", namespace.trim());
      if (ownerId.trim()) fd.append("owner_id", ownerId.trim());

      const { data } = await secureAxios.post(
        `${API_BASE}/admin/bulk-upload`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      setJobId(data.job_id);
    } catch (e) {
      console.error(e);
      alert(`Upload failed: ${e.message || "Unknown error"}`);
    } finally {
      setSubmitting(false);
    }
  };

  // Poll status
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer = null;

    const tick = async () => {
      try {
        const { data } = await secureAxios.get(`${API_BASE}/admin/bulk-upload/${jobId}`);
        if (cancelled) return;
        setStatus(data);
        if (data.state === "done" || data.state === "error") return;
        timer = setTimeout(tick, 1500);
      } catch (e) {
        console.error(e);
      }
    };

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Bulk Upload</h1>
        <div className="text-sm text-gray-500">
          Upload many docs at once (multiple files or a single ZIP).
        </div>
      </header>

      <section className="grid md:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div
            ref={dropRef}
            className="border-2 border-dashed rounded-xl p-6 text-center hover:bg-gray-50"
          >
            <div className="font-medium mb-2">Drag & Drop files here</div>
            <div className="text-xs text-gray-500 mb-3">
              Allowed: pdf, docx, pptx, xlsx, csv, txt, md, png, jpg, jpeg
            </div>
            <input
              type="file"
              multiple
              className="block w-full text-sm"
              onChange={(e) => setFiles((prev) => [...prev, ...Array.from(e.target.files)])}
            />
            <div className="mt-4 border rounded-lg text-left max-h-48 overflow-auto">
              {files.length === 0 ? (
                <div className="text-sm text-gray-400 p-3">No files added</div>
              ) : (
                files.map((f, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 border-b last:border-b-0">
                    <div>
                      <div className="text-sm">{f.name}</div>
                      <div className="text-xs text-gray-500">{prettyBytes(f.size)}</div>
                    </div>
                    <button
                      className="text-xs px-2 py-1 rounded hover:bg-gray-100"
                      onClick={() => removeFile(i)}
                    >
                      Remove
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="space-y-2 border rounded-xl p-4">
            <label className="text-sm font-medium">Or upload a ZIP</label>
            <input
              type="file"
              accept=".zip"
              onChange={(e) => setZipFile(e.target.files?.[0] || null)}
              className="block w-full text-sm"
            />
            {zipFile ? (
              <div className="text-xs text-gray-600">
                Selected: {zipFile.name} ({prettyBytes(zipFile.size)})
              </div>
            ) : null}
          </div>
        </div>

        <div className="space-y-4">
          <div className="border rounded-xl p-4 space-y-3">
            <div className="text-sm font-medium mb-1">Options</div>

            <label className="text-sm block">
              <div className="text-gray-600 mb-1">Visibility</div>
              <select
                className="w-full border rounded-lg px-3 py-2"
                value={visibility}
                onChange={(e) => setVisibility(e.target.value)}
              >
                <option value="private">Private (owner-only)</option>
                <option value="global">Global (searchable by all)</option>
              </select>
            </label>

            <label className="text-sm block">
              <div className="text-gray-600 mb-1">Namespace (optional)</div>
              <input
                className="w-full border rounded-lg px-3 py-2"
                placeholder="e.g., opentext, invoices, hr-policies"
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
              />
            </label>

            <label className="text-sm block">
              <div className="text-gray-600 mb-1">Owner ID (admin override, optional)</div>
              <input
                className="w-full border rounded-lg px-3 py-2"
                placeholder="Defaults to current user"
                value={ownerId}
                onChange={(e) => setOwnerId(e.target.value)}
              />
            </label>

            <div className="text-xs text-gray-500">
              Selected files: <b>{files.length}</b> • Total size: <b>{prettyBytes(totalSize)}</b>
            </div>

            <button
              disabled={submitting}
              onClick={submit}
              className="w-full rounded-lg bg-black text-white py-2 hover:opacity-90 disabled:opacity-50"
            >
              {submitting ? "Uploading..." : "Start Bulk Upload"}
            </button>
          </div>

          {jobId && (
            <div className="border rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-medium">Job Status</div>
                <div className="text-xs text-gray-500">Job ID: {jobId}</div>
              </div>
              {!status ? (
                <div className="text-sm text-gray-500">Initializing…</div>
              ) : (
                <>
                  <div className="text-sm mb-2">
                    State: <span className="font-medium">{status.state?.toUpperCase?.() || "-"}</span>
                  </div>
                  <div className="max-h-60 overflow-auto border rounded">
                    {status.files?.map((f, i) => (
                      <div
                        key={i}
                        className="grid grid-cols-5 gap-2 px-3 py-2 border-b last:border-b-0 text-sm"
                      >
                        <div className="col-span-3 truncate" title={f.filename}>{f.filename}</div>
                        <div className="text-xs">{f.status}</div>
                        <div className="text-xs text-gray-500 truncate">{f.message || ""}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
