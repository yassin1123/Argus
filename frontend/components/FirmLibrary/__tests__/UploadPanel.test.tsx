import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import UploadPanel from "../UploadPanel";

// Mock the API client at module-load time. Each test pulls the mocked
// uploadFirmContent off the mock to assert / control return values.
vi.mock("@/lib/api/firmLibrary", () => ({
  uploadFirmContent: vi.fn(),
}));

// Late import so the mock is attached before consumers see it.
import { uploadFirmContent } from "@/lib/api/firmLibrary";

const mockedUpload = uploadFirmContent as unknown as ReturnType<typeof vi.fn>;

const FIRM_ID = "00000000-0000-0000-0000-000000000001";

function makeFile(name: string, content = "hello world", type = "text/markdown") {
  return new File([content], name, { type });
}

afterEach(() => {
  cleanup();
  mockedUpload.mockReset();
});

describe("UploadPanel", () => {
  it("renders the form fields the spec calls for", () => {
    render(<UploadPanel firmId={FIRM_ID} />);

    expect(screen.getByRole("button", { name: /upload file/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/^title/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^category/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^description/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/sector tags/i)).toBeInTheDocument();
    // Add to library button is present and visible.
    expect(screen.getByRole("button", { name: /add to library/i })).toBeInTheDocument();
  });

  it("disables submit until a file, title, and category are all set", async () => {
    const user = userEvent.setup();
    render(<UploadPanel firmId={FIRM_ID} />);

    const submit = screen.getByRole("button", { name: /add to library/i });
    expect(submit).toBeDisabled();

    // Add a file (which auto-fills title from the stem).
    const fileInput = screen.getByTestId("firm-library-file-input") as HTMLInputElement;
    await user.upload(fileInput, makeFile("ma_screen.md"));

    // Title is auto-filled but category is still empty → still disabled.
    expect(submit).toBeDisabled();

    await user.selectOptions(screen.getByLabelText(/^category/i), "playbook");
    expect(submit).toBeEnabled();

    // Clearing title disables again.
    await user.clear(screen.getByLabelText(/^title/i));
    expect(submit).toBeDisabled();
  });

  it("submits with FormData containing the right fields", async () => {
    const user = userEvent.setup();
    mockedUpload.mockResolvedValueOnce({
      firm_content: {
        id: "fc-1",
        firm_id: FIRM_ID,
        title: "M&A target screen",
        category: "playbook",
        description: null,
        intended_modes: ["due_diligence"],
        sector_tags: ["payments"],
        source_filename: "ma_screen.md",
        file_hash: "abc",
        trust_level: "firm_vetted",
        uploaded_by: null,
        uploaded_at: "2026-05-09T00:00:00Z",
        retired_at: null,
        retired_by: null,
        chunk_count: 3,
        metadata: {},
      },
      ingest: { cached: false, chunks_written: 3 },
    });

    render(<UploadPanel firmId={FIRM_ID} />);
    const fileInput = screen.getByTestId("firm-library-file-input") as HTMLInputElement;
    await user.upload(fileInput, makeFile("ma_screen.md"));

    await user.clear(screen.getByLabelText(/^title/i));
    await user.type(screen.getByLabelText(/^title/i), "M&A target screen");
    await user.selectOptions(screen.getByLabelText(/^category/i), "playbook");
    await user.click(screen.getByRole("button", { name: /due diligence/i }));
    // Add a sector via Enter.
    await user.type(screen.getByLabelText(/sector tags/i), "payments{Enter}");

    await user.click(screen.getByRole("button", { name: /add to library/i }));

    await waitFor(() => expect(mockedUpload).toHaveBeenCalledTimes(1));
    const [firmIdArg, inputArg] = mockedUpload.mock.calls[0];
    expect(firmIdArg).toBe(FIRM_ID);
    expect(inputArg.title).toBe("M&A target screen");
    expect(inputArg.category).toBe("playbook");
    expect(inputArg.intendedModes).toEqual(["due_diligence"]);
    expect(inputArg.sectorTags).toEqual(["payments"]);
    expect(inputArg.file).toBeInstanceOf(File);
    expect((inputArg.file as File).name).toBe("ma_screen.md");
  });

  it("shows a loading state while the upload is pending", async () => {
    const user = userEvent.setup();
    let resolveUpload: ((v: unknown) => void) | undefined;
    mockedUpload.mockImplementationOnce(
      () => new Promise((res) => { resolveUpload = res as (v: unknown) => void; }),
    );

    render(<UploadPanel firmId={FIRM_ID} />);
    const fileInput = screen.getByTestId("firm-library-file-input") as HTMLInputElement;
    await user.upload(fileInput, makeFile("primer.md"));
    await user.selectOptions(screen.getByLabelText(/^category/i), "sector_primer");
    await user.click(screen.getByRole("button", { name: /add to library/i }));

    // Submit button now reads "Indexing…" and the helper-text appears.
    expect(await screen.findByRole("button", { name: /indexing/i })).toBeInTheDocument();
    expect(screen.getByText(/parsing, chunking, and embedding/i)).toBeInTheDocument();

    resolveUpload?.({
      firm_content: {
        id: "fc-2",
        firm_id: FIRM_ID,
        title: "primer",
        category: "sector_primer",
        description: null,
        intended_modes: [],
        sector_tags: [],
        source_filename: "primer.md",
        file_hash: "x",
        trust_level: "firm_vetted",
        uploaded_by: null,
        uploaded_at: "now",
        retired_at: null,
        retired_by: null,
        chunk_count: 1,
        metadata: {},
      },
      ingest: { cached: false, chunks_written: 1 },
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /add to library/i })).toBeInTheDocument(),
    );
  });

  it("shows a friendly error toast when the upload fails", async () => {
    const user = userEvent.setup();
    mockedUpload.mockRejectedValueOnce(new Error("Server unreachable (502)"));

    render(<UploadPanel firmId={FIRM_ID} />);
    const fileInput = screen.getByTestId("firm-library-file-input") as HTMLInputElement;
    await user.upload(fileInput, makeFile("p.md"));
    await user.selectOptions(screen.getByLabelText(/^category/i), "playbook");
    await user.click(screen.getByRole("button", { name: /add to library/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/server unreachable/i);
  });

  it("shows a success toast with the chunk count and resets the form", async () => {
    const user = userEvent.setup();
    mockedUpload.mockResolvedValueOnce({
      firm_content: {
        id: "fc-3",
        firm_id: FIRM_ID,
        title: "Diligence Framework v3",
        category: "framework",
        description: null,
        intended_modes: [],
        sector_tags: [],
        source_filename: "dilig.md",
        file_hash: "h",
        trust_level: "firm_vetted",
        uploaded_by: null,
        uploaded_at: "now",
        retired_at: null,
        retired_by: null,
        chunk_count: 7,
        metadata: {},
      },
      ingest: { cached: false, chunks_written: 7 },
    });

    render(<UploadPanel firmId={FIRM_ID} />);
    const fileInput = screen.getByTestId("firm-library-file-input") as HTMLInputElement;
    await user.upload(fileInput, makeFile("dilig.md"));
    await user.selectOptions(screen.getByLabelText(/^category/i), "framework");
    await user.click(screen.getByRole("button", { name: /add to library/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/added "diligence framework v3"/i);
    expect(status).toHaveTextContent(/7 chunks indexed/);

    // Form reset: title field empty, category cleared.
    await waitFor(() => {
      expect((screen.getByLabelText(/^title/i) as HTMLInputElement).value).toBe("");
    });
    expect((screen.getByLabelText(/^category/i) as HTMLSelectElement).value).toBe("");
  });

  it("rejects unsupported file extensions before any network call", async () => {
    render(<UploadPanel firmId={FIRM_ID} />);
    const fileInput = screen.getByTestId("firm-library-file-input") as HTMLInputElement;
    // user-event's `upload` mimics the browser's accept-attribute filter
    // and silently drops non-matching files, so our own UI validation
    // never gets a chance to reject. fireEvent.change goes around it.
    fireEvent.change(fileInput, {
      target: { files: [makeFile("logo.png", "fake", "image/png")] },
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/unsupported file type/i);
    expect(mockedUpload).not.toHaveBeenCalled();
  });
});
