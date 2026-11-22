import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import secureAxios from "../../utils/secureAxios";
import { sanitizeDisplayError } from "./BulkUpload";

export const metadataReviewPath = (jobId, documentId) => (
  `/admin/bulk-upload/${encodeURIComponent(jobId)}/documents/${encodeURIComponent(documentId)}/metadata-review`
);

function reviewFromResponse(data) {
  return data?.review || data?.metadata_review || data || {};
}

function reviewFields(review) {
  const fields = review?.review_fields ?? review?.selected_fields ?? review?.fields ?? [];
  return Array.isArray(fields) ? fields : [];
}

function fieldKey(field) {
  return String(field?.key ?? field?.name ?? field?.id ?? "");
}

function fieldValue(field) {
  if (Object.prototype.hasOwnProperty.call(field, "draft_value")) return field.draft_value;
  if (Object.prototype.hasOwnProperty.call(field, "current_value")) return field.current_value;
  return field?.original_value ?? "";
}

function allowedActions(review) {
  const actions = review?.allowed_actions ?? review?.available_actions ?? review?.available_transitions;
  if (Array.isArray(actions)) {
    return new Set(actions.map((item) => String(
      typeof item === "string" ? item : item?.action ?? item?.name,
    ).toLowerCase().replace(/-/g, "_")));
  }
  if (actions && typeof actions === "object") {
    return new Set(Object.keys(actions).filter((key) => actions[key] === true).map((key) => key.toLowerCase()));
  }
  return new Set();
}

function editableField(field) {
  const type = String(field?.value_type ?? field?.type ?? "string").toLowerCase();
  return field?.read_only !== true
    && field?.is_read_only !== true
    && field?.readonly !== true
    && field?.editable !== false
    && (type !== "enum" || Array.isArray(field?.allowed_values))
    && ["string", "text", "number", "integer", "boolean", "date", "datetime", "enum"].includes(type);
}

function inputValue(value) {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function isBlank(value) {
  return value == null || (typeof value === "string" && value.trim() === "");
}

export function validateReviewFields(fields, drafts) {
  const errors = {};
  fields.forEach((field) => {
    const key = fieldKey(field);
    if (!key) return;
    const value = drafts[key];
    const label = field.label || key;
    const required = field.required === true || field.is_required === true;
    if (required && isBlank(value)) {
      errors[key] = "This field is required.";
      return;
    }
    if (isBlank(value) || !editableField(field)) return;
    const type = String(field.value_type ?? field.type ?? "string").toLowerCase();
    if (type === "number" && !Number.isFinite(Number(value))) errors[key] = "Enter a valid number.";
    if (type === "integer" && (!Number.isFinite(Number(value)) || !Number.isInteger(Number(value)))) {
      errors[key] = "Enter a whole number.";
    }
    if (Array.isArray(field.allowed_values) && !field.allowed_values.some(
      (allowed) => String(allowed) === String(value),
    )) {
      errors[key] = `${label} must be one of the allowed values.`;
    }
  });
  return errors;
}

function responseFieldErrors(error) {
  const data = error?.data;
  const source = data?.field_errors ?? data?.details?.field_errors ?? data?.errors;
  if (Array.isArray(source)) {
    return source.reduce((result, item) => {
      const key = item?.field ?? item?.key;
      if (key) result[key] = sanitizeDisplayError(item?.message, "Invalid value.");
      return result;
    }, {});
  }
  if (source && typeof source === "object") {
    return Object.fromEntries(Object.entries(source).map(([key, value]) => [
      key,
      sanitizeDisplayError(value?.message ?? value, "Invalid value."),
    ]));
  }
  return {};
}

function previewPath(review) {
  const value = review?.original_preview_url ?? review?.preview_url ?? review?.original_preview?.url;
  if (review?.preview_supported === false || review?.original_preview?.supported === false) return "";
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "";
  return value;
}

function displayValue(value) {
  if (value == null || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function freshSubmissionId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = Math.random() * 16 | 0;
    return (char === "x" ? random : (random & 0x3 | 0x8)).toString(16);
  });
}

function actionPath(base, action) {
  return `${base}/${action.replace(/_/g, "-")}`;
}

export default function MetadataReview() {
  const { jobId, documentId } = useParams();
  const [review, setReview] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [savingAction, setSavingAction] = useState("");
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [conflicted, setConflicted] = useState(false);
  const [startRequired, setStartRequired] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewError, setPreviewError] = useState("");

  const basePath = metadataReviewPath(jobId, documentId);
  const fields = useMemo(() => reviewFields(review), [review]);
  const actions = useMemo(() => allowedActions(review), [review]);
  const localErrors = useMemo(() => validateReviewFields(fields, drafts), [fields, drafts]);
  const canReview = Boolean(review && review.reviewable !== false);
  const hasVersion = review?.expected_version != null || review?.version != null;
  const selectedFields = Array.isArray(review?.selected_fields) ? review.selected_fields : [];
  const derivedReviewFields = Array.isArray(review?.derived_review_fields) ? review.derived_review_fields : [];
  const reviewNotRequired = review?.verification_mode === "NEVER" || review?.review_required === false;

  const loadReview = useCallback(async () => {
    setLoading(true);
    setGeneralError("");
    try {
      const { data } = await secureAxios.get(basePath);
      const latest = reviewFromResponse(data);
      const nextDrafts = {};
      reviewFields(latest).forEach((field) => {
        const key = fieldKey(field);
        if (key) nextDrafts[key] = fieldValue(field);
      });
      setReview(latest);
      setDrafts(nextDrafts);
      setFieldErrors({});
      setConflicted(false);
      setStartRequired(false);
    } catch (error) {
      if (error?.status === 404) {
        setStartRequired(true);
      } else {
        setGeneralError(sanitizeDisplayError(error, "Metadata review could not be loaded."));
      }
    } finally {
      setLoading(false);
    }
  }, [basePath]);

  useEffect(() => {
    loadReview();
  }, [loadReview]);

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setPreviewUrl("");
    setPreviewError("");
    const path = review ? previewPath(review) : "";
    if (!path) return undefined;
    secureAxios.get(path, { responseType: "blob" }).then(({ data }) => {
      if (!active) return;
      const type = data?.type || "application/octet-stream";
      if (!type.startsWith("application/pdf") && !type.startsWith("image/")) {
        setPreviewError("Preview format is not supported.");
        return;
      }
      objectUrl = URL.createObjectURL(data);
      setPreviewUrl(objectUrl);
    }).catch((error) => {
      if (active) setPreviewError(sanitizeDisplayError(error, "Original preview is unavailable."));
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [review]);

  const startReview = async () => {
    if (savingAction) return;
    setSavingAction("start");
    setGeneralError("");
    try {
      const { data } = await secureAxios.post(`${basePath}/start`, {});
      const latest = reviewFromResponse(data);
      const nextDrafts = {};
      reviewFields(latest).forEach((field) => {
        const key = fieldKey(field);
        if (key) nextDrafts[key] = fieldValue(field);
      });
      setReview(latest);
      setDrafts(nextDrafts);
      setStartRequired(false);
    } catch (error) {
      setGeneralError(sanitizeDisplayError(error, "Metadata review could not be started."));
    } finally {
      setSavingAction("");
    }
  };

  const updateDraft = (key, value) => {
    setDrafts((current) => ({ ...current, [key]: value }));
    setFieldErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
    setGeneralError("");
  };

  const performAction = async (action) => {
    if (!actions.has(action) || savingAction) return;
    const errors = validateReviewFields(fields, drafts);
    setFieldErrors(errors);
    setGeneralError("");
    if (action !== "save_draft" && Object.keys(errors).length) return;
    if (!hasVersion) return;

    setSavingAction(action);
    try {
      const values = {};
      fields.forEach((field) => {
        const key = fieldKey(field);
        if (!key || !editableField(field)) return;
        const type = String(field.value_type ?? field.type ?? "string").toLowerCase();
        const value = drafts[key];
        values[key] = isBlank(value) ? null
          : type === "number" || type === "integer" ? Number(value)
            : type === "boolean" && typeof value === "string" ? value === "true"
              : value;
      });
      const { data } = await secureAxios.post(actionPath(basePath, action), {
        expected_version: review.expected_version ?? review.version,
        submission_id: freshSubmissionId(),
        values,
      });
      const updated = reviewFromResponse(data);
      if (Object.keys(updated).length) {
        const returnedFields = reviewFields(updated);
        if (returnedFields.length) {
          const originals = new Map(fields.map((field) => [fieldKey(field), field.original_value]));
          const safeFields = returnedFields.map((field) => {
            const key = fieldKey(field);
            return originals.has(key) ? { ...field, original_value: originals.get(key) } : field;
          });
          const hasActions = updated.allowed_actions != null
            || updated.available_actions != null
            || updated.available_transitions != null;
          setReview((current) => ({
            ...current,
            ...updated,
            review_fields: safeFields,
            ...(hasActions ? {} : { allowed_actions: [] }),
          }));
          const nextDrafts = {};
          safeFields.forEach((field) => {
            const key = fieldKey(field);
            if (key) nextDrafts[key] = fieldValue(field);
          });
          setDrafts(nextDrafts);
        } else {
          const hasActions = updated.allowed_actions != null
            || updated.available_actions != null
            || updated.available_transitions != null;
          setReview((current) => ({
            ...current,
            ...updated,
            ...(hasActions ? {} : { allowed_actions: [] }),
          }));
        }
      }
      setFieldErrors({});
      setConflicted(false);
    } catch (error) {
      const returnedErrors = responseFieldErrors(error);
      if (Object.keys(returnedErrors).length) setFieldErrors(returnedErrors);
      if (error?.status === 409) {
        setConflicted(true);
        setGeneralError("This document changed in another session. Your edits are preserved; reload the latest version to continue.");
      } else {
        setGeneralError(sanitizeDisplayError(error, "The review action could not be completed."));
      }
    } finally {
      setSavingAction("");
    }
  };

  const history = review?.audit_history ?? review?.history ?? [];
  const noReview = review && (
    reviewNotRequired
    || review.reviewable === false
    || review.no_review_required === true
    || reviewFields(review).length === 0
  );

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link className="text-sm text-blue-700 hover:underline" to="/console/bulk-upload">← Bulk Upload</Link>
          <h1 className="mt-2 text-2xl font-semibold">Metadata review</h1>
          <p className="mt-1 text-sm text-gray-500">{review?.filename || review?.document?.filename || `Document ${documentId}`}</p>
        </div>
        {review && <div className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium">
          Review status: {review.review_status ?? review.status ?? "Not reported"}
        </div>}
      </header>

      <section className="grid gap-3 sm:grid-cols-3" aria-label="Independent document statuses">
        <div className="rounded-lg border p-3 text-sm">
          <div className="text-xs text-gray-500">Upload processing</div>
          <div className="mt-1 font-medium">{review?.processing_status ?? review?.document?.processing_status ?? "Not reported"}</div>
        </div>
        <div className="rounded-lg border p-3 text-sm">
          <div className="text-xs text-gray-500">Search index</div>
          <div className="mt-1 font-medium">{review?.index_status ?? review?.search_index_status ?? review?.document?.index_status ?? "Not reported"}</div>
        </div>
        <div className="rounded-lg border p-3 text-sm">
          <div className="text-xs text-gray-500">Metadata verification</div>
          <div className="mt-1 font-medium">{review?.verification_status ?? review?.document?.verification_status ?? "Not verified"}</div>
        </div>
      </section>

      {!loading && review && (
        <section className="rounded-xl border p-4" aria-label="Verification policy">
          <h2 className="font-semibold">Verification policy</h2>
          <p className="mt-1 text-sm">Verification mode: {review.verification_mode ?? "Not reported"}</p>
          {review.confidence_threshold != null && (
            <p className="mt-1 text-sm">Confidence threshold: {String(review.confidence_threshold)}</p>
          )}
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <h3 className="text-sm font-medium">Selected fields</h3>
              {selectedFields.length ? (
                <ul className="mt-1 space-y-1 text-sm">
                  {selectedFields.map((field) => {
                    const key = String(field?.key ?? field?.name ?? field);
                    const confidenceSupplied = field?.confidence_supplied !== false
                      && Object.prototype.hasOwnProperty.call(field ?? {}, "confidence");
                    return (
                      <li key={key}>
                        {key}
                        {confidenceSupplied && (
                          <span className="ml-2 text-gray-600">
                            Confidence: {field.confidence == null ? "Unavailable" : String(field.confidence)}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : <p className="mt-1 text-sm text-gray-500">None reported.</p>}
            </div>
            <div>
              <h3 className="text-sm font-medium">Derived review fields</h3>
              {derivedReviewFields.length ? (
                <ul className="mt-1 space-y-1 text-sm">
                  {derivedReviewFields.map((field) => (
                    <li key={String(field?.key ?? field?.name ?? field)}>
                      {String(field?.key ?? field?.name ?? field)}
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-1 text-sm text-gray-500">None required.</p>}
            </div>
          </div>
        </section>
      )}

      {loading ? <p className="rounded-lg border p-4 text-sm text-gray-500">Loading review…</p> : null}
      {!loading && generalError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
          {generalError}
          {conflicted && (
            <button type="button" className="ml-2 font-medium underline" onClick={loadReview}>
              Discard local edits and reload latest version
            </button>
          )}
        </div>
      )}
      {!loading && startRequired && (
        <div className="rounded-lg border bg-gray-50 p-4 text-sm" role="status">
          <p>Metadata review has not been started for this document.</p>
          <button
            type="button"
            className="mt-3 rounded border px-3 py-2 font-medium"
            disabled={Boolean(savingAction)}
            onClick={startReview}
          >
            {savingAction === "start" ? "Starting review..." : "Start metadata review"}
          </button>
        </div>
      )}
      {!loading && noReview && (
        <div className="rounded-lg border bg-gray-50 p-4 text-sm" role="status">
          {reviewNotRequired
            ? "Metadata review is not required."
            : "No metadata review is available for this document."}
        </div>
      )}

      {!loading && review && !noReview && (
        <>
          <div className="grid gap-5 lg:grid-cols-2">
            <section className="min-h-72 rounded-xl border p-4" aria-label="Original document preview">
              <h2 className="mb-3 font-semibold">Original document</h2>
              {previewUrl ? (
                <iframe className="h-[32rem] w-full rounded border" title="Original document preview" src={previewUrl} />
              ) : previewError ? (
                <p className="rounded bg-gray-50 p-4 text-sm text-gray-600">{previewError}</p>
              ) : previewPath(review) ? (
                <p className="p-4 text-sm text-gray-500">Loading original preview…</p>
              ) : (
                <p className="rounded bg-gray-50 p-4 text-sm text-gray-600">Original preview is not supported for this document.</p>
              )}
            </section>

            <section className="space-y-4 rounded-xl border p-4" aria-label="Metadata review fields">
              <div>
                <h2 className="font-semibold">Derived review fields</h2>
                <p className="mt-1 text-xs text-gray-500">Only fields selected by the review service for review are editable.</p>
              </div>
              {fields.map((field) => {
                const key = fieldKey(field);
                const type = String(field.value_type ?? field.type ?? "string").toLowerCase();
                const editable = editableField(field);
                const options = Array.isArray(field.allowed_values) && field.allowed_values.length
                  ? field.allowed_values
                  : null;
                const error = fieldErrors[key] || localErrors[key];
                return (
                  <div className="space-y-2 border-t pt-3" key={key}>
                    <label className="block text-sm font-medium" htmlFor={`metadata-${key}`}>
                      {field.label || key}{field.required === true || field.is_required === true ? <span className="text-red-700"> *</span> : null}
                    </label>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="rounded bg-gray-50 p-2 text-xs">
                        <div className="mb-1 text-gray-500">Original extracted value</div>
                        <div className="break-words" data-testid={`original-${key}`}>{displayValue(field.original_value)}</div>
                      </div>
                      <div className="rounded bg-gray-50 p-2 text-xs">
                        <div className="mb-1 text-gray-500">Draft value</div>
                        {editable ? (
                          options ? (
                            <select
                              id={`metadata-${key}`}
                              className="w-full rounded border bg-white p-2 text-sm"
                              value={inputValue(drafts[key])}
                              onChange={(event) => updateDraft(key, event.target.value)}
                              aria-invalid={Boolean(error)}
                            >
                              <option value="">Select a value</option>
                              {options.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}
                            </select>
                          ) : type === "boolean" ? (
                            <select
                              id={`metadata-${key}`}
                              className="w-full rounded border bg-white p-2 text-sm"
                              value={drafts[key] === true ? "true" : drafts[key] === false ? "false" : ""}
                              onChange={(event) => updateDraft(key, event.target.value === "" ? "" : event.target.value === "true")}
                              aria-invalid={Boolean(error)}
                            >
                              <option value="">Select a value</option>
                              <option value="true">True</option>
                              <option value="false">False</option>
                            </select>
                          ) : (
                            <input
                              id={`metadata-${key}`}
                              className="w-full rounded border bg-white p-2 text-sm"
                              type={type === "number" || type === "integer" ? "number" : type === "date" ? "date" : type === "datetime" ? "datetime-local" : "text"}
                              step={type === "integer" ? "1" : undefined}
                              value={inputValue(drafts[key])}
                              onChange={(event) => updateDraft(key, event.target.value)}
                              aria-invalid={Boolean(error)}
                            />
                          )
                        ) : <div className="break-words p-2 text-sm" id={`metadata-${key}`}>{displayValue(drafts[key] ?? field.original_value)}</div>}
                      </div>
                    </div>
                    {(field.confidence ?? field.confidence_score) != null && (
                      <div className="text-xs text-gray-600">Confidence: {String(field.confidence ?? field.confidence_score)}</div>
                    )}
                    {error && <div className="text-xs text-red-700" role="alert">{error}</div>}
                    {!editable && <div className="text-xs text-gray-500">Read-only</div>}
                  </div>
                );
              })}

              {canReview && (
                <div className="flex flex-wrap gap-2 border-t pt-4">
                  {["save_draft", "verify", "submit"].map((action) => {
                    if (!actions.has(action)) return null;
                    const label = action === "save_draft" ? "Save Draft" : action === "verify" ? "Verify" : "Submit";
                    const invalid = !hasVersion || (action !== "save_draft" && Object.keys(localErrors).length > 0);
                    return (
                      <button
                        key={action}
                        type="button"
                        disabled={Boolean(savingAction) || invalid}
                        onClick={() => performAction(action)}
                        className={`rounded-lg px-4 py-2 text-sm ${action === "submit" ? "bg-black text-white" : "border"} disabled:cursor-not-allowed disabled:opacity-50`}
                      >
                        {savingAction === action ? `${label}…` : label}
                      </button>
                    );
                  })}
                  {!actions.size && <p className="text-sm text-gray-500">No review actions are currently available.</p>}
                </div>
              )}
              {review.expected_version != null || review.version != null ? (
                <p className="text-xs text-gray-500">Version {review.expected_version ?? review.version}</p>
              ) : null}
            </section>
          </div>

          <section className="rounded-xl border p-4" aria-label="Metadata review audit history">
            <h2 className="font-semibold">Audit history</h2>
            {!Array.isArray(history) || history.length === 0 ? (
              <p className="mt-2 text-sm text-gray-500">No audit history is available.</p>
            ) : (
              <ol className="mt-3 divide-y">
                {history.map((item, index) => (
                  <li className="flex flex-wrap gap-x-4 gap-y-1 py-2 text-sm" key={item.id ?? item.sequence ?? index}>
                    <span className="font-medium">{item.action ?? "Review action"}</span>
                    {(item.version ?? item.sequence) != null && <span className="text-gray-600">Version / sequence {item.version ?? item.sequence}</span>}
                    {item.actor && <span className="text-gray-600">{item.actor}</span>}
                    {(item.timestamp ?? item.created_at ?? item.time) && (
                      <time className="text-gray-500" dateTime={item.timestamp ?? item.created_at ?? item.time}>
                        {item.timestamp ?? item.created_at ?? item.time}
                      </time>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </div>
  );
}
