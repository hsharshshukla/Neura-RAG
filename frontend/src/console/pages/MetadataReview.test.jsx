import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";

import secureAxios from "../../utils/secureAxios";
import BulkUpload, { BULK_UPLOAD_LIMITS_PATH } from "./BulkUpload";
import MetadataReview, { metadataReviewPath, validateReviewFields } from "./MetadataReview";

jest.mock("../../utils/secureAxios", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));

jest.mock("react-router-dom", () => ({
  Link: ({ to, children, ...props }) => <a href={to} {...props}>{children}</a>,
  useParams: () => ({ jobId: "job-1", documentId: "doc-1" }),
}));

global.IS_REACT_ACT_ENVIRONMENT = true;

const reviewPath = metadataReviewPath("job-1", "doc-1");
const baseReview = {
  document_id: "doc-1",
  filename: "source.pdf",
  expected_version: 7,
  reviewable: true,
  review_status: "DRAFT",
  verification_status: "PENDING",
  processing_status: "COMPLETED",
  index_status: "NOT_READY",
  allowed_actions: ["save_draft", "verify", "submit"],
  review_fields: [
    {
      key: "title",
      label: "Title",
      type: "string",
      required: true,
      original_value: "Extracted title",
      draft_value: "Current draft",
    },
    {
      key: "pages",
      label: "Pages",
      type: "integer",
      required: true,
      original_value: 2,
      draft_value: 2,
      read_only: true,
    },
  ],
};

const mountedRoots = [];

async function render(element) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoots.push([root, container]);
  await act(async () => root.render(element));
  return container;
}

async function click(element) {
  await act(async () => element.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

async function change(element, value) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      element.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype,
      "value",
    ).set;
    setter.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function button(container, label) {
  return [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === label);
}

function setupReview(data = baseReview) {
  secureAxios.get.mockImplementation(async (url) => {
    if (url === reviewPath) return { data: { review: data, correlation_id: "00000000-0000-4000-8000-000000000001" } };
    throw new Error(`Unexpected GET ${url}`);
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  global.URL.createObjectURL = jest.fn(() => "blob:original-preview");
  global.URL.revokeObjectURL = jest.fn();
});

afterEach(async () => {
  while (mountedRoots.length) {
    const [root, container] = mountedRoots.pop();
    await act(async () => root.unmount());
    container.remove();
  }
});

test("renders only selected fields, enforces declared editability and required/type validation", async () => {
  setupReview({
    ...baseReview,
    review_fields: [
      { key: "title", label: "Title", type: "string", required: true, original_value: "", draft_value: "" },
      { key: "category", label: "Category", type: "enum", required: true, allowed_values: ["A", "B"], draft_value: "A" },
      { key: "count", label: "Count", type: "integer", draft_value: 2 },
      { key: "fixed", label: "Read-only", type: "string", read_only: true, original_value: "fixed" },
    ],
  });
  const container = await render(<MetadataReview />);
  expect(container.textContent).not.toContain("Not selected");
  expect(container.querySelector("#metadata-fixed").tagName).toBe("DIV");
  expect(container.querySelector("#metadata-category").tagName).toBe("SELECT");
  expect(container.querySelector("#metadata-count").type).toBe("number");
  expect(button(container, "Verify").disabled).toBe(true);
  expect(validateReviewFields([{ key: "n", type: "integer" }], { n: "2.5" })).toEqual({ n: "Enter a whole number." });
});

test("keeps the original extraction visible beside the editable draft", async () => {
  setupReview();
  secureAxios.post.mockResolvedValueOnce({
    data: {
      expected_version: 8,
      allowed_actions: ["save_draft"],
      review_fields: [{ ...baseReview.review_fields[0], original_value: "Mutated by response", draft_value: "Changed draft" }],
    },
  });
  const container = await render(<MetadataReview />);
  expect(container.querySelector('[data-testid="original-title"]').textContent).toBe("Extracted title");
  expect(container.querySelector("#metadata-title").value).toBe("Current draft");
  await change(container.querySelector("#metadata-title"), "Changed draft");
  await click(button(container, "Save Draft"));
  expect(container.querySelector('[data-testid="original-title"]').textContent).toBe("Extracted title");
  expect(container.querySelector("#metadata-title").value).toBe("Changed draft");
});

test("renders confidence indicators only when the backend supplies confidence", async () => {
  setupReview({
    ...baseReview,
    review_fields: [
      { key: "scored", type: "string", original_value: "A", draft_value: "A", confidence: 0.83 },
      { key: "unscored", type: "string", original_value: "B", draft_value: "B" },
    ],
  });
  const container = await render(<MetadataReview />);
  expect(container.textContent).toContain("Confidence: 0.83");
  expect(container.textContent.match(/Confidence:/g)).toHaveLength(1);
});

test("renders authoritative mode, selected-field confidence, and server-derived review fields", async () => {
  setupReview({
    ...baseReview,
    verification_mode: "LOW_CONFIDENCE",
    confidence_threshold: 0.8,
    selected_fields: [
      { key: "title", confidence: 0.91, confidence_supplied: true },
      { key: "document_type", confidence: null, confidence_supplied: true },
    ],
    derived_review_fields: ["title"],
    review_fields: [{ key: "title", type: "string", draft_value: "Draft" }],
  });
  const container = await render(<MetadataReview />);
  expect(container.textContent).toContain("Verification mode: LOW_CONFIDENCE");
  expect(container.textContent).toContain("Confidence threshold: 0.8");
  expect(container.textContent).toContain("title");
  expect(container.textContent).toContain("Confidence: 0.91");
  expect(container.textContent).toContain("Confidence: Unavailable");
  expect(container.querySelector('[aria-label="Metadata review fields"]').textContent).toContain("title");
  expect(container.querySelector('[aria-label="Metadata review fields"]').textContent).not.toContain("document_type");
});

test("shows no-review result and does not invent policy-selected fields", async () => {
  setupReview({
    ...baseReview,
    reviewable: false,
    verification_mode: "NEVER",
    review_required: false,
    selected_fields: [{ key: "metadata", confidence: null, confidence_supplied: true }],
    derived_review_fields: [],
    allowed_actions: [],
    review_fields: [],
  });
  const container = await render(<MetadataReview />);
  expect(container.textContent).toContain("Metadata review is not required.");
  expect(container.textContent).toContain("Verification mode: NEVER");
  expect(container.textContent).toContain("Confidence: Unavailable");
  expect(container.textContent).toContain("None required.");
  expect(container.querySelector('[aria-label="Metadata review fields"]')).toBeNull();
  expect(container.querySelectorAll("button")).toHaveLength(0);
});

test("gates action buttons on server transitions, required values, and posts current version with fresh submission ID", async () => {
  setupReview({
    ...baseReview,
    allowed_actions: ["save_draft", "verify"],
    review_fields: [
      { key: "title", type: "string", required: true, draft_value: "" },
      { key: "count", type: "integer", draft_value: "3" },
    ],
  });
  secureAxios.post.mockResolvedValueOnce({ data: { expected_version: 8, review_status: "DRAFT" } });
  const container = await render(<MetadataReview />);
  expect(button(container, "Save Draft").disabled).toBe(false);
  expect(button(container, "Verify").disabled).toBe(true);
  expect(button(container, "Submit")).toBeFalsy();
  expect(container.textContent).toContain("This field is required.");
  await click(button(container, "Save Draft"));
  const [url, payload] = secureAxios.post.mock.calls[0];
  expect(url).toBe(`${reviewPath}/save-draft`);
  expect(payload.expected_version).toBe(7);
  expect(payload.values.count).toBe(3);
  expect(payload.submission_id).toMatch(/^[0-9a-f-]{36}$/i);
  expect(payload.submission_id).not.toBe("");
});

test("surfaces field-level validation errors returned by the server", async () => {
  setupReview();
  const serverError = new Error("Invalid metadata");
  serverError.data = { field_errors: { title: "Title is rejected." } };
  secureAxios.post.mockRejectedValueOnce(serverError);
  const container = await render(<MetadataReview />);
  await click(button(container, "Verify"));
  expect(container.textContent).toContain("Title is rejected.");
});

test("preserves edits on stale-version conflict until explicit latest-version reload", async () => {
  setupReview();
  const conflict = new Error("Conflict");
  conflict.status = 409;
  secureAxios.post.mockRejectedValueOnce(conflict);
  const container = await render(<MetadataReview />);
  await change(container.querySelector("#metadata-title"), "My unsaved edit");
  await click(button(container, "Verify"));
  expect(container.textContent).toContain("changed in another session");
  expect(container.querySelector("#metadata-title").value).toBe("My unsaved edit");
  expect(button(container, "Discard local edits and reload latest version")).toBeTruthy();

  secureAxios.get.mockImplementation(async () => ({
    data: { ...baseReview, expected_version: 8, review_fields: [{ ...baseReview.review_fields[0], draft_value: "Latest server value" }] },
  }));
  await click(button(container, "Discard local edits and reload latest version"));
  expect(container.querySelector("#metadata-title").value).toBe("Latest server value");
});

test("displays available audit history action, sequence, actor, and time", async () => {
  setupReview({
    ...baseReview,
    audit_history: [{
      action: "VERIFY",
      sequence: 4,
      actor: "reviewer@example.test",
      timestamp: "2026-11-22T10:00:00Z",
    }],
  });
  const container = await render(<MetadataReview />);
  expect(container.textContent).toContain("VERIFY");
  expect(container.textContent).toContain("Version / sequence 4");
  expect(container.textContent).toContain("reviewer@example.test");
  expect(container.querySelector('time[datetime="2026-11-22T10:00:00Z"]')).toBeTruthy();
});

test("uses authenticated preview fetch and safely falls back when unsupported", async () => {
  setupReview({ ...baseReview, preview_supported: false, preview_url: "/api/v1/admin/docs/doc-1/preview" });
  const unsupported = await render(<MetadataReview />);
  expect(unsupported.textContent).toContain("Original preview is not supported");
  expect(secureAxios.get).toHaveBeenCalledTimes(1);

  setupReview({ ...baseReview, preview_url: "/api/v1/admin/docs/doc-1/preview" });
  secureAxios.get.mockImplementation(async (url) => (
    url === reviewPath ? { data: { ...baseReview, preview_url: "/api/v1/admin/docs/doc-1/preview" } }
      : { data: new Blob(["pdf"], { type: "application/pdf" }) }
  ));
  const supported = await render(<MetadataReview />);
  await act(async () => Promise.resolve());
  expect(secureAxios.get).toHaveBeenCalledWith("/api/v1/admin/docs/doc-1/preview", { responseType: "blob" });
  expect(supported.querySelector('iframe[title="Original document preview"]').getAttribute("src")).toBe("blob:original-preview");
});

test("does not fetch an external preview URL", async () => {
  setupReview({ ...baseReview, preview_url: "https://external.invalid/document.pdf" });
  const container = await render(<MetadataReview />);
  expect(container.textContent).toContain("Original preview is not supported");
  expect(secureAxios.get).toHaveBeenCalledTimes(1);
});

test("links eligible bulk-upload rows to review and separates verification from processing/index readiness", async () => {
  const job = {
    job_id: "job-1",
    state: "completed",
    processing_complete: true,
    search_index_ready: false,
    documents: [{
      document_id: "doc-1",
      filename: "source.pdf",
      status: "completed",
      metadata_review_available: true,
      verification_status: "PENDING",
    }],
  };
  secureAxios.get.mockImplementation(async (url) => (
    url === BULK_UPLOAD_LIMITS_PATH ? { data: { max_files: 1 } } : { data: job }
  ));
  secureAxios.post.mockResolvedValueOnce({ data: { job_id: "job-1" } });
  const upload = await render(<BulkUpload />);
  await act(async () => {
    const input = upload.querySelector('input[type="file"]');
    Object.defineProperty(input, "files", { configurable: true, value: [new File(["x"], "source.pdf")] });
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await click(button(upload, "Start bulk upload"));
  expect(upload.querySelector('a[href="/console/bulk-upload/job-1/documents/doc-1/review"]')).toBeTruthy();
  expect(upload.textContent).toContain("Search index not ready");

  setupReview();
  const review = await render(<MetadataReview />);
  expect(review.textContent).toContain("Upload processing");
  expect(review.textContent).toContain("COMPLETED");
  expect(review.textContent).toContain("Search index");
  expect(review.textContent).toContain("NOT_READY");
  expect(review.textContent).toContain("Metadata verification");
  expect(review.textContent).toContain("PENDING");
});
