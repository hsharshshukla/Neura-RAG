import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import secureAxios from "../../utils/secureAxios";

export const BULK_UPLOAD_PATH = "/admin/bulk-upload";
export const BULK_UPLOAD_LIMITS_PATH = `${BULK_UPLOAD_PATH}/limits`;

const FAILED_STATES = new Set(["error", "failed"]);
const TERMINAL_JOB_STATES = new Set(["error", "failed", "cancelled", "canceled"]);
const COMPLETE_PROCESSING_STATES = new Set([
  "complete", "completed", "done", "indexing", "processing_complete", "ready",
]);

function firstNumber(source, keys) {
  for (const key of keys) {
    const value = Number(source?.[key]);
    if (Number.isFinite(value) && value >= 0) return value;
  }
  return null;
}

function normalizeAllowedTypes(value) {
  const values = Array.isArray(value) ? value : typeof value === "string" ? value.split(",") : [];
  return values
    .map((item) => String(item).trim().toLowerCase())
    .filter(Boolean)
    .map((item) => (item.includes("/") || item.startsWith(".") ? item : `.${item}`));
}

export function normalizeLimits(response) {
  const source = response?.limits || response || {};
  return {
    maxFiles: firstNumber(source, ["max_files", "max_file_count", "max_files_per_job", "max_upload_files"]),
    maxFileSize: firstNumber(source, [
      "max_file_size_bytes", "max_bytes_per_file", "max_file_bytes", "max_upload_file_bytes",
    ]),
    maxTotalSize: firstNumber(source, [
      "max_total_size_bytes", "max_batch_size_bytes", "max_upload_bytes",
    ]),
    allowedTypes: normalizeAllowedTypes(
      source.allowed_extensions
        || source.allowed_file_types
        || source.allowed_types
        || source.allowed_mime_types,
    ),
  };
}

export function prettyBytes(value) {
  if (!Number.isFinite(Number(value))) return "Not configured";
  let amount = Number(value);
  const units = ["B", "KB", "MB", "GB"];
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function extensionOf(filename = "") {
  const dot = filename.lastIndexOf(".");
  return dot < 0 ? "" : filename.slice(dot).toLowerCase();
}

function typeIsAllowed(file, allowedTypes) {
  if (!allowedTypes.length) return true;
  const extension = extensionOf(file.name);
  const mime = String(file.type || "").toLowerCase();
  return allowedTypes.some((allowed) => {
    if (allowed.startsWith(".")) return allowed === extension;
    if (allowed.endsWith("/*")) return mime.startsWith(allowed.slice(0, -1));
    return allowed === mime;
  });
}

export function validateFiles(files, limits) {
  if (!limits) return [];
  const errors = [];
  if (limits.maxFiles != null && files.length > limits.maxFiles) {
    errors.push(`Select no more than ${limits.maxFiles} files per upload.`);
  }
  files.forEach((file) => {
    if (limits.maxFileSize != null && file.size > limits.maxFileSize) {
      errors.push(`${file.name} exceeds the ${prettyBytes(limits.maxFileSize)} per-file limit.`);
    }
    if (!typeIsAllowed(file, limits.allowedTypes)) {
      errors.push(`${file.name} is not an allowed file type.`);
    }
  });
  const totalSize = files.reduce((sum, file) => sum + (Number(file.size) || 0), 0);
  if (limits.maxTotalSize != null && totalSize > limits.maxTotalSize) {
    errors.push(`The selected files exceed the ${prettyBytes(limits.maxTotalSize)} total limit.`);
  }
  return errors;
}

export function sanitizeDisplayError(value, fallback = "The request could not be completed.") {
  const text = typeof value === "string"
    ? value
    : typeof value?.message === "string"
      ? value.message
      : fallback;
  return text
    .replace(/[<>]/g, "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 500) || fallback;
}

function documentsFrom(status) {
  return status?.documents || status?.files || [];
}

function documentState(document) {
  return String(document?.status || document?.state || "queued").toLowerCase();
}

function documentId(document) {
  return document?.document_id || document?.id || document?.doc_id || document?.file_id;
}

function documentName(document) {
  return document?.filename || document?.name || document?.title || "Unnamed document";
}

function documentError(document) {
  const value = document?.sanitized_error || document?.error_message || document?.error;
  if (value == null && FAILED_STATES.has(documentState(document))) return document?.message;
  return value;
}

export function processingIsComplete(status) {
  if (typeof status?.processing_complete === "boolean") return status.processing_complete;
  return COMPLETE_PROCESSING_STATES.has(String(status?.state || status?.status || "").toLowerCase());
}

function readinessValue(status) {
  if (typeof status?.search_index_ready === "boolean") return status.search_index_ready;
  if (typeof status?.index_ready === "boolean") return status.index_ready;
  const state = String(
    status?.search_index_status || status?.index_status || status?.readiness?.state || "",
  ).toLowerCase();
  if (!state) {
    return String(status?.state || status?.status || "").toLowerCase() === "ready" ? true : null;
  }
  return state === "ready" || state === "complete" || state === "completed";
}

export function pollingShouldStop(status) {
  if (!status) return false;
  if (status.polling_complete === true) return true;
  const state = String(status.state || status.status || "").toLowerCase();
  if (TERMINAL_JOB_STATES.has(state)) return true;
  const ready = readinessValue(status);
  return ready === true;
}

function statusLabel(state) {
  return state.replace(/_/g, " ");
}

export default function BulkUpload({ pollInterval = 1500 }) {
  const [files, setFiles] = useState([]);
  const [limits, setLimits] = useState(null);
  const [limitsLoading, setLimitsLoading] = useState(true);
  const [limitsError, setLimitsError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState("");
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null);
  const [pollError, setPollError] = useState("");
  const [pollVersion, setPollVersion] = useState(0);
  const [retrying, setRetrying] = useState([]);
  const inputRef = useRef(null);

  const loadLimits = useCallback(async () => {
    setLimitsLoading(true);
    setLimitsError("");
    try {
      const { data } = await secureAxios.get(BULK_UPLOAD_LIMITS_PATH);
      setLimits(normalizeLimits(data));
    } catch (error) {
      setLimits(null);
      setLimitsError(sanitizeDisplayError(error, "Upload limits could not be loaded."));
    } finally {
      setLimitsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLimits();
  }, [loadLimits]);

  const addFiles = useCallback((incoming) => {
    const additions = Array.from(incoming || []);
    if (!additions.length) return;
    setFiles((current) => [...current, ...additions]);
    setRequestError("");
  }, []);

  const onDrop = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    addFiles(event.dataTransfer?.files);
  }, [addFiles]);

  const totalSize = useMemo(
    () => files.reduce((sum, file) => sum + (Number(file.size) || 0), 0),
    [files],
  );
  const preflightErrors = useMemo(() => validateFiles(files, limits), [files, limits]);
  const canSubmit = files.length > 0
    && !preflightErrors.length
    && !limitsLoading
    && !limitsError
    && !submitting;

  const removeFile = (index) => {
    setFiles((current) => current.filter((_, currentIndex) => currentIndex !== index));
  };

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setRequestError("");
    setStatus(null);
    setPollError("");
    try {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      const { data } = await secureAxios.post(BULK_UPLOAD_PATH, form);
      if (!data?.job_id) throw new Error("The server did not return a bulk-upload job ID.");
      setJobId(data.job_id);
      if (data.documents || data.files || data.state || data.status) setStatus(data);
    } catch (error) {
      setRequestError(sanitizeDisplayError(error, "Bulk upload failed."));
    } finally {
      setSubmitting(false);
    }
  };

  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer;

    const poll = async () => {
      try {
        const { data } = await secureAxios.get(`${BULK_UPLOAD_PATH}/${jobId}`);
        if (cancelled) return;
        setStatus(data);
        setPollError("");
        if (!pollingShouldStop(data)) timer = setTimeout(poll, pollInterval);
      } catch (error) {
        if (!cancelled) setPollError(sanitizeDisplayError(error, "Job status could not be loaded."));
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, pollInterval, pollVersion]);

  const retryDocument = async (document) => {
    const id = documentId(document);
    if (!id || !jobId) return;
    setRetrying((current) => [...current, id]);
    setRequestError("");
    try {
      const { data } = await secureAxios.post(`${BULK_UPLOAD_PATH}/${jobId}/retry`, {
        document_ids: [id],
      });
      if (data?.job_id && data.job_id !== jobId) setJobId(data.job_id);
      if (data?.documents || data?.files || data?.state || data?.status) setStatus(data);
      setPollVersion((version) => version + 1);
    } catch (error) {
      setRequestError(sanitizeDisplayError(error, `Retry failed for ${documentName(document)}.`));
    } finally {
      setRetrying((current) => current.filter((currentId) => currentId !== id));
    }
  };

  const documents = documentsFrom(status);
  const processingComplete = processingIsComplete(status);
  const searchReady = readinessValue(status);
  const jobState = String(status?.state || status?.status || "queued").toLowerCase();

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Bulk Upload</h1>
        <p className="mt-1 text-sm text-gray-500">
          Add documents to organizational knowledge through the managed TKP ingestion service.
        </p>
      </header>

      <section className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div
            className="rounded-xl border-2 border-dashed p-6 text-center hover:bg-gray-50"
            onDragOver={(event) => event.preventDefault()}
            onDrop={onDrop}
          >
            <div className="font-medium">Drag and drop files here</div>
            <div className="my-2 text-xs text-gray-500">or choose multiple files</div>
            <button
              type="button"
              className="rounded-lg bg-black px-4 py-2 text-sm text-white hover:opacity-90"
              onClick={() => inputRef.current?.click()}
            >
              Choose files
            </button>
            <input
              ref={inputRef}
              aria-label="Choose files"
              className="sr-only"
              type="file"
              multiple
              accept={limits?.allowedTypes.join(",") || undefined}
              onChange={(event) => {
                addFiles(event.target.files);
                event.target.value = "";
              }}
            />
          </div>

          <div className="overflow-hidden rounded-xl border">
            <div className="flex items-center justify-between border-b bg-gray-50 px-4 py-3 text-sm">
              <span className="font-medium">Selected documents ({files.length})</span>
              <span className="text-gray-500">{prettyBytes(totalSize)}</span>
            </div>
            {files.length === 0 ? (
              <p className="p-4 text-sm text-gray-500">No files selected.</p>
            ) : files.map((file, index) => (
              <div className="flex items-center justify-between gap-4 border-b px-4 py-3 last:border-b-0" key={`${file.name}-${file.size}-${index}`}>
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium" title={file.name}>{file.name}</div>
                  <div className="text-xs text-gray-500">{prettyBytes(file.size)}</div>
                </div>
                <button
                  type="button"
                  className="rounded px-2 py-1 text-xs hover:bg-gray-100"
                  onClick={() => removeFile(index)}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>

          {preflightErrors.length > 0 && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
              <div className="font-medium">Fix these selection issues before uploading:</div>
              <ul className="mt-1 list-disc pl-5">
                {preflightErrors.map((error) => <li key={error}>{error}</li>)}
              </ul>
              <p className="mt-2 text-xs">The server will validate every file again when it is submitted.</p>
            </div>
          )}

          {requestError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{requestError}</div>}

          <button
            type="button"
            disabled={!canSubmit}
            onClick={submit}
            className="w-full rounded-lg bg-black py-2 text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Uploading…" : "Start bulk upload"}
          </button>
        </div>

        <aside className="h-fit rounded-xl border p-4" aria-label="Configured upload limits">
          <h2 className="text-sm font-semibold">Configured upload limits</h2>
          {limitsLoading ? (
            <p className="mt-3 text-sm text-gray-500">Loading limits…</p>
          ) : limitsError ? (
            <div className="mt-3 text-sm text-red-700">
              <p>{limitsError}</p>
              <button type="button" className="mt-2 underline" onClick={loadLimits}>Retry</button>
            </div>
          ) : (
            <dl className="mt-3 space-y-3 text-sm">
              <div><dt className="text-gray-500">Files per upload</dt><dd className="font-medium">{limits.maxFiles ?? "Backend validated"}</dd></div>
              <div><dt className="text-gray-500">Maximum per file</dt><dd className="font-medium">{prettyBytes(limits.maxFileSize)}</dd></div>
              <div><dt className="text-gray-500">Maximum total size</dt><dd className="font-medium">{prettyBytes(limits.maxTotalSize)}</dd></div>
              <div>
                <dt className="text-gray-500">Allowed types</dt>
                <dd className="break-words font-medium">{limits.allowedTypes.join(", ") || "Backend validated"}</dd>
              </div>
            </dl>
          )}
        </aside>
      </section>

      {jobId && (
        <section className="rounded-xl border p-4" aria-label="Bulk upload job">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3">
            <div>
              <h2 className="font-semibold">Upload job</h2>
              <div className="text-xs text-gray-500">Job ID: {jobId}</div>
            </div>
            <div className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium capitalize">{statusLabel(jobState)}</div>
          </div>

          {!status ? <p className="py-4 text-sm text-gray-500">Waiting for processing status…</p> : (
            <>
              <div className="grid gap-3 py-4 sm:grid-cols-2">
                <div className={`rounded-lg border p-3 text-sm ${processingComplete ? "border-green-200 bg-green-50" : "bg-gray-50"}`}>
                  <div className="font-medium">{processingComplete ? "Processing complete" : "Processing documents"}</div>
                  <div className="mt-1 text-xs text-gray-600">
                    {processingComplete ? "Every document has reached a processing result." : "Document processing is still in progress."}
                  </div>
                </div>
                <div className={`rounded-lg border p-3 text-sm ${searchReady === true ? "border-green-200 bg-green-50" : "border-amber-200 bg-amber-50"}`}>
                  <div className="font-medium">
                    {searchReady === true
                      ? "Search index ready"
                      : searchReady === false
                        ? "Search index not ready"
                        : "Search readiness pending"}
                  </div>
                  <div className="mt-1 text-xs text-gray-600">
                    {searchReady === true
                      ? "Successfully processed documents can now appear in search."
                      : searchReady === false
                        ? "Processing completion does not mean the documents are searchable yet."
                        : "TKP has not reported whether the documents are searchable yet."}
                  </div>
                </div>
              </div>

              <div className="overflow-hidden rounded-lg border">
                {documents.length === 0 ? (
                  <p className="p-3 text-sm text-gray-500">No document results have been reported yet.</p>
                ) : documents.map((document, index) => {
                  const state = documentState(document);
                  const id = documentId(document);
                  const error = documentError(document);
                  const canRetry = FAILED_STATES.has(state) && document.retryable === true && Boolean(id);
                  return (
                    <div className="grid gap-2 border-b px-3 py-3 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_8rem_minmax(0,1fr)_auto] sm:items-center" key={id || `${documentName(document)}-${index}`}>
                      <div className="truncate text-sm font-medium" title={documentName(document)}>{documentName(document)}</div>
                      <div className="text-xs font-medium uppercase tracking-wide">{statusLabel(state)}</div>
                      <div className="text-xs text-red-700">{error ? sanitizeDisplayError(error) : ""}</div>
                      {canRetry && (
                        <button
                          type="button"
                          disabled={retrying.includes(id)}
                          className="rounded border px-3 py-1 text-xs hover:bg-gray-50 disabled:opacity-50"
                          onClick={() => retryDocument(document)}
                        >
                          {retrying.includes(id) ? "Retrying…" : `Retry ${documentName(document)}`}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {pollError && (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
              {pollError}{" "}
              <button type="button" className="underline" onClick={() => setPollVersion((version) => version + 1)}>Retry status check</button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
