import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";

import secureAxios from "../../utils/secureAxios";
import BulkUpload, {
  BULK_UPLOAD_LIMITS_PATH,
  BULK_UPLOAD_PATH,
  pollingShouldStop,
} from "./BulkUpload";

jest.mock("../../utils/secureAxios", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));

global.IS_REACT_ACT_ENVIRONMENT = true;

const limits = {
  max_files: 3,
  max_file_size_bytes: 10,
  max_total_size_bytes: 20,
  allowed_extensions: [".pdf", ".txt"],
};

const mountedRoots = [];

async function renderPage(props = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoots.push([root, container]);
  await act(async () => {
    root.render(<BulkUpload {...props} />);
  });
  return container;
}

async function chooseFiles(container, files) {
  const input = container.querySelector('input[type="file"]');
  Object.defineProperty(input, "files", { configurable: true, value: files });
  await act(async () => {
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function click(element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function buttonNamed(container, name) {
  return [...container.querySelectorAll("button")].find((button) => button.textContent === name);
}

beforeEach(() => {
  jest.clearAllMocks();
  secureAxios.get.mockImplementation(async (url) => {
    if (url === BULK_UPLOAD_LIMITS_PATH) return { data: limits };
    throw new Error(`Unexpected GET ${url}`);
  });
});

afterEach(async () => {
  while (mountedRoots.length) {
    const [root, container] = mountedRoots.pop();
    await act(async () => root.unmount());
    container.remove();
  }
  jest.useRealTimers();
});

test("does not treat processing completion as search readiness", () => {
  expect(pollingShouldStop({ state: "completed", processing_complete: true })).toBe(false);
  expect(pollingShouldStop({ state: "completed", search_index_ready: false })).toBe(false);
  expect(pollingShouldStop({ state: "completed", search_index_ready: true })).toBe(true);
  expect(pollingShouldStop({ state: "ready" })).toBe(true);
});

test("surfaces backend limits and blocks count, size, total-size, and type violations", async () => {
  const container = await renderPage();
  await chooseFiles(container, [
    new File(["12345"], "first.pdf", { type: "application/pdf" }),
    new File(["12345678901"], "large.txt", { type: "text/plain" }),
    new File(["12345"], "bad.exe", { type: "application/octet-stream" }),
    new File(["1"], "extra.pdf", { type: "application/pdf" }),
  ]);

  expect(container.textContent).toContain("Files per upload3");
  expect(container.textContent).toContain("Select no more than 3 files");
  expect(container.textContent).toContain("large.txt exceeds the 10 B per-file limit");
  expect(container.textContent).toContain("bad.exe is not an allowed file type");
  expect(container.textContent).toContain("exceed the 20 B total limit");
  expect(buttonNamed(container, "Start bulk upload").disabled).toBe(true);
  expect(secureAxios.post).not.toHaveBeenCalled();
});

test("renders mixed document states, sanitized errors, and separate readiness messaging", async () => {
  const job = {
    job_id: "job-1",
    state: "completed",
    processing_complete: true,
    search_index_ready: false,
    documents: [
      { document_id: "ok-1", filename: "ready.pdf", status: "succeeded", retryable: false },
      { document_id: "work-1", filename: "working.txt", status: "processing", retryable: false },
      { document_id: "bad-1", filename: "failed.pdf", status: "failed", retryable: true, sanitized_error: "<unsafe> parse error" },
      { document_id: "bad-2", filename: "permanent.pdf", status: "failed", retryable: false, sanitized_error: "Unsupported content" },
    ],
  };
  secureAxios.post.mockResolvedValueOnce({ data: { job_id: "job-1" } });
  secureAxios.get.mockImplementation(async (url) => (
    url === BULK_UPLOAD_LIMITS_PATH ? { data: limits } : { data: job }
  ));

  const container = await renderPage();
  await chooseFiles(container, [new File(["ok"], "ready.pdf", { type: "application/pdf" })]);
  await click(buttonNamed(container, "Start bulk upload"));

  expect(container.textContent).toContain("ready.pdf");
  expect(container.textContent).toContain("working.txt");
  expect(container.textContent).toContain("failed.pdf");
  expect(container.textContent).toContain("permanent.pdf");
  expect(container.textContent).toContain("unsafe parse error");
  expect(container.textContent).not.toContain("<unsafe>");
  expect(container.textContent).toContain("Processing complete");
  expect(container.textContent).toContain("Search index not ready");
  expect(buttonNamed(container, "Retry failed.pdf")).toBeTruthy();
  expect(buttonNamed(container, "Retry ready.pdf")).toBeFalsy();
  expect(buttonNamed(container, "Retry permanent.pdf")).toBeFalsy();
});

test("keeps polling after processing and stops when the search index is ready", async () => {
  jest.useFakeTimers();
  const statuses = [
    { job_id: "job-2", state: "completed", processing_complete: true, search_index_ready: false, documents: [] },
    { job_id: "job-2", state: "completed", processing_complete: true, search_index_ready: true, documents: [] },
  ];
  let statusCall = 0;
  secureAxios.post.mockResolvedValueOnce({ data: { job_id: "job-2" } });
  secureAxios.get.mockImplementation(async (url) => {
    if (url === BULK_UPLOAD_LIMITS_PATH) return { data: limits };
    return { data: statuses[Math.min(statusCall++, statuses.length - 1)] };
  });

  const container = await renderPage({ pollInterval: 25 });
  await chooseFiles(container, [new File(["ok"], "ready.pdf", { type: "application/pdf" })]);
  await click(buttonNamed(container, "Start bulk upload"));
  expect(container.textContent).toContain("Search index not ready");

  await act(async () => jest.advanceTimersByTime(25));
  expect(container.textContent).toContain("Search index ready");
  await act(async () => jest.advanceTimersByTime(100));
  expect(statusCall).toBe(2);
});

test("shows upload errors and retries only the selected retryable failed document", async () => {
  secureAxios.post.mockRejectedValueOnce(new Error("Backend rejected the batch"));
  const first = await renderPage();
  await chooseFiles(first, [new File(["ok"], "ready.pdf", { type: "application/pdf" })]);
  await click(buttonNamed(first, "Start bulk upload"));
  expect(first.textContent).toContain("Backend rejected the batch");

  const job = {
    job_id: "job-3",
    state: "failed",
    processing_complete: true,
    search_index_ready: false,
    documents: [
      { document_id: "success-id", filename: "success.pdf", status: "succeeded", retryable: false },
      { document_id: "failure-id", filename: "failure.pdf", status: "failed", retryable: true, sanitized_error: "Temporary failure" },
    ],
  };
  secureAxios.post
    .mockResolvedValueOnce({ data: { job_id: "job-3" } })
    .mockResolvedValueOnce({ data: { ...job, state: "running" } });
  secureAxios.get.mockImplementation(async (url) => (
    url === BULK_UPLOAD_LIMITS_PATH ? { data: limits } : { data: job }
  ));
  const second = await renderPage();
  await chooseFiles(second, [new File(["ok"], "success.pdf", { type: "application/pdf" })]);
  await click(buttonNamed(second, "Start bulk upload"));
  await click(buttonNamed(second, "Retry failure.pdf"));

  expect(secureAxios.post).toHaveBeenLastCalledWith(`${BULK_UPLOAD_PATH}/job-3/retry`, {
    document_ids: ["failure-id"],
  });
  expect(JSON.stringify(secureAxios.post.mock.calls.at(-1))).not.toContain("success-id");
});
