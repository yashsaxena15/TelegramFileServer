import { useState, useEffect, useRef } from "react";
import {
  X,
  Download,
  ExternalLink,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  FileText,
  FileSpreadsheet,
  Presentation,
  BookOpen,
  Copy,
  Check,
  RotateCw,
  Columns,
  List
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { renderAsync } from "docx-preview";
import { ReactReader } from "react-reader";
import JSZip from "jszip";
import Prism from "prismjs";
import "prismjs/themes/prism-tomorrow.css";
// Basic syntax highlighting languages
import "prismjs/components/prism-python";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-json";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-css";
import "prismjs/components/prism-markup"; // html/xml
import "prismjs/components/prism-sql";
import "prismjs/components/prism-yaml";

import { SpreadsheetViewer } from "./SpreadsheetViewer";
import { PresentationViewer } from "./PresentationViewer";
import { toast } from "sonner";

interface DocumentReaderModalProps {
  url: string;
  fileName: string;
  fileExtension?: string;
  onClose: () => void;
}

export const DocumentReaderModal = ({
  url,
  fileName,
  fileExtension,
  onClose,
}: DocumentReaderModalProps) => {
  const ext = (fileExtension || fileName.split(".").pop() || "").toLowerCase();

  const SPREADSHEET_EXTS = ["xlsx", "xls", "xlsm", "xlsb", "xltx", "csv", "tsv", "ods"];
  const isSpreadsheet = SPREADSHEET_EXTS.includes(ext);
  const PRESENTATION_EXTS = ["pptx", "ppt", "ppsx", "potx", "pptm", "potm"];
  const isPresentation = PRESENTATION_EXTS.includes(ext);
  const isPdf = ext === "pdf";
  const isEpub = ext === "epub";
  const isComic = ext === "cbz" || ext === "cbr";
  const isDocx = ext === "docx";
  const isMarkdown = ext === "md" || ext === "markdown";
  const isCodeOrText = [
    "txt", "log", "json", "py", "js", "ts", "jsx", "tsx", "html", "css",
    "sh", "bash", "yml", "yaml", "xml", "sql", "env", "ini", "conf"
  ].includes(ext);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fontSize, setFontSize] = useState<number>(14);

  // E-book state
  const [epubLocation, setEpubLocation] = useState<string | number>(0);

  // Comic state
  const [comicImages, setComicImages] = useState<string[]>([]);
  const [comicMode, setComicMode] = useState<"webtoon" | "paginated">("webtoon");
  const [comicPageIndex, setComicPageIndex] = useState(0);

  const modalRef = useRef<HTMLDivElement>(null);
  const docxContainerRef = useRef<HTMLDivElement>(null);

  // Keyboard shortcut for Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Load document content depending on type
  useEffect(() => {
    let isMounted = true;
    setIsLoading(true);
    setError(null);

    const loadContent = async () => {
      try {
        if (isSpreadsheet || isPresentation) {
          if (isMounted) setIsLoading(false);
          return;
        }

        if (isCodeOrText || isMarkdown) {
          const res = await fetch(url);
          if (!res.ok) throw new Error(`Failed to fetch file (${res.status})`);
          const text = await res.text();
          if (isMounted) {
            setTextContent(text);
            setIsLoading(false);
            setTimeout(() => Prism.highlightAll(), 50);
          }
        } else if (isDocx) {
          const res = await fetch(url);
          if (!res.ok) throw new Error(`Failed to fetch docx (${res.status})`);
          const blob = await res.blob();
          if (isMounted && docxContainerRef.current) {
            docxContainerRef.current.innerHTML = "";
            await renderAsync(blob, docxContainerRef.current, undefined, {
              className: "docx-viewer-content",
              inWrapper: false,
              ignoreWidth: false,
              ignoreHeight: false,
            });
            setIsLoading(false);
          }
        } else if (isComic) {
          const res = await fetch(url);
          if (!res.ok) throw new Error(`Failed to fetch comic archive (${res.status})`);
          const arrayBuffer = await res.arrayBuffer();
          const zip = await JSZip.loadAsync(arrayBuffer);
          const imagePromises: Promise<{ name: string; url: string }>[] = [];

          const IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"];

          zip.forEach((relativePath, zipEntry) => {
            const lower = relativePath.toLowerCase();
            if (!zipEntry.dir && IMAGE_EXTS.some((e) => lower.endsWith(e))) {
              imagePromises.push(
                zipEntry.async("blob").then((blob) => ({
                  name: relativePath,
                  url: URL.createObjectURL(blob),
                }))
              );
            }
          });

          const loaded = await Promise.all(imagePromises);
          // Natural alphanumeric sort
          loaded.sort((a, b) =>
            a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" })
          );

          if (isMounted) {
            setComicImages(loaded.map((img) => img.url));
            setIsLoading(false);
          }
        } else {
          // For PDF or EPUB, let viewer component load stream directly
          setIsLoading(false);
        }
      } catch (err: any) {
        if (isMounted) {
          logger_error("Error loading document", err);
          setError(err.message || "Failed to load document preview");
          setIsLoading(false);
        }
      }
    };

    loadContent();

    return () => {
      isMounted = false;
      // Revoke comic image object URLs
      comicImages.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [url, ext]);

  const logger_error = (msg: string, e: any) => {
    console.error(msg, e);
  };

  const handleCopy = () => {
    if (!textContent) return;
    navigator.clipboard.writeText(textContent);
    setCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const toggleFullscreen = () => {
    if (!modalRef.current) return;
    if (!document.fullscreenElement) {
      modalRef.current.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  const downloadUrl = `${url}&download=1`;

  return (
    <div
      ref={modalRef}
      className="fixed inset-0 z-50 bg-black/90 flex flex-col backdrop-blur-sm animate-in fade-in duration-200"
    >
      {/* Top Navigation Bar */}
      <header className="h-14 bg-zinc-900/90 border-b border-zinc-800 px-4 flex items-center justify-between select-none shrink-0 z-20">
        <div className="flex items-center gap-3 min-w-0 pr-4">
          <div className="p-2 bg-primary/10 rounded text-primary">
            {isPdf ? (
              <FileText className="w-5 h-5 text-red-400" />
            ) : isEpub || isComic ? (
              <BookOpen className="w-5 h-5 text-emerald-400" />
            ) : isDocx ? (
              <FileText className="w-5 h-5 text-blue-400" />
            ) : isSpreadsheet ? (
              <FileSpreadsheet className="w-5 h-5 text-emerald-400" />
            ) : isPresentation ? (
              <Presentation className="w-5 h-5 text-orange-400" />
            ) : (
              <FileText className="w-5 h-5 text-amber-400" />
            )}
          </div>
          <div className="min-w-0">
            <h2 className="text-sm sm:text-base font-medium text-zinc-100 truncate max-w-xs sm:max-w-md md:max-w-lg">
              {fileName}
            </h2>
            <p className="text-xs text-zinc-400 uppercase tracking-wider font-semibold">
              {isSpreadsheet
                ? "Spreadsheet preview"
                : isPresentation
                ? "Presentation preview"
                : `${ext} preview`}
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-1.5 sm:gap-2">
          {/* Code/Text Zoom Controls */}
          {(isCodeOrText || isMarkdown) && (
            <div className="hidden sm:flex items-center gap-1 bg-zinc-800 rounded p-0.5 mr-2">
              <button
                onClick={() => setFontSize((s) => Math.max(10, s - 2))}
                className="p-1.5 text-zinc-400 hover:text-white rounded hover:bg-zinc-700 transition"
                title="Decrease font size"
              >
                <ZoomOut className="w-4 h-4" />
              </button>
              <span className="text-xs text-zinc-300 px-1 font-mono">{fontSize}px</span>
              <button
                onClick={() => setFontSize((s) => Math.min(24, s + 2))}
                className="p-1.5 text-zinc-400 hover:text-white rounded hover:bg-zinc-700 transition"
                title="Increase font size"
              >
                <ZoomIn className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Copy Button for text files */}
          {(isCodeOrText || isMarkdown) && textContent && (
            <button
              onClick={handleCopy}
              className="p-2 text-zinc-400 hover:text-white rounded hover:bg-zinc-800 transition"
              title="Copy content"
            >
              {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
            </button>
          )}

          {/* Comic Mode Toggle */}
          {isComic && comicImages.length > 0 && (
            <div className="flex items-center bg-zinc-800 rounded p-0.5 mr-2">
              <button
                onClick={() => setComicMode("webtoon")}
                className={`px-2 py-1 text-xs rounded transition ${
                  comicMode === "webtoon"
                    ? "bg-primary text-primary-foreground font-semibold"
                    : "text-zinc-400 hover:text-white"
                }`}
                title="Continuous Vertical Scroll (Webtoon mode)"
              >
                Scroll
              </button>
              <button
                onClick={() => setComicMode("paginated")}
                className={`px-2 py-1 text-xs rounded transition ${
                  comicMode === "paginated"
                    ? "bg-primary text-primary-foreground font-semibold"
                    : "text-zinc-400 hover:text-white"
                }`}
                title="Page Flip Mode"
              >
                Flip
              </button>
            </div>
          )}

          {/* Open in New Tab Button */}
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 text-zinc-400 hover:text-white rounded hover:bg-zinc-800 transition"
            title="Open in new browser tab"
          >
            <ExternalLink className="w-4 h-4" />
          </a>

          {/* Download Direct */}
          <a
            href={downloadUrl}
            className="p-2 text-zinc-400 hover:text-white rounded hover:bg-zinc-800 transition"
            title="Download file"
          >
            <Download className="w-4 h-4" />
          </a>

          {/* Fullscreen Toggle */}
          <button
            onClick={toggleFullscreen}
            className="p-2 text-zinc-400 hover:text-white rounded hover:bg-zinc-800 transition"
            title="Toggle fullscreen"
          >
            {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>

          {/* Close Modal */}
          <button
            onClick={onClose}
            className="p-2 text-zinc-400 hover:text-red-400 rounded hover:bg-zinc-800 transition ml-1"
            title="Close (Esc)"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 relative overflow-hidden bg-zinc-950 flex flex-col">
        {isLoading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-zinc-950/80 z-30">
            <div className="w-10 h-10 border-4 border-primary border-t-transparent rounded-full animate-spin"></div>
            <p className="text-sm text-zinc-400">Loading {fileName}...</p>
          </div>
        )}

        {error && (
          <div className="m-auto max-w-md p-6 bg-red-950/40 border border-red-800/60 rounded-xl text-center">
            <p className="text-red-300 font-semibold mb-2">Could not preview document</p>
            <p className="text-xs text-red-400/80 mb-4">{error}</p>
            <a
              href={downloadUrl}
              className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-md text-sm font-medium transition"
            >
              <Download className="w-4 h-4" /> Download File Instead
            </a>
          </div>
        )}

        {/* 1. PDF Viewer */}
        {isPdf && !error && (
          <iframe
            src={`${url}#toolbar=1&navpanes=1&statusbar=1`}
            className="w-full h-full border-none bg-zinc-900"
            title={fileName}
          />
        )}

        {/* 2. EPUB E-Book Reader */}
        {isEpub && !error && (
          <div className="w-full h-full relative">
            <ReactReader
              url={url}
              location={epubLocation}
              locationChanged={(loc: string) => setEpubLocation(loc)}
              epubOptions={{
                flow: "paginated",
                width: "100%",
                height: "100%",
              }}
              swipeable
            />
          </div>
        )}

        {/* 3. Comic Book Viewer (CBZ / CBR) */}
        {isComic && !error && (
          <div className="w-full h-full overflow-auto bg-zinc-950 flex flex-col items-center p-4">
            {comicImages.length === 0 ? (
              <p className="m-auto text-zinc-500">No images found in comic archive.</p>
            ) : comicMode === "webtoon" ? (
              /* Continuous Webtoon Scroll Mode */
              <div className="w-full max-w-3xl flex flex-col items-center gap-1">
                {comicImages.map((src, i) => (
                  <img
                    key={i}
                    src={src}
                    alt={`Page ${i + 1}`}
                    loading="lazy"
                    className="w-full h-auto shadow-lg select-none"
                  />
                ))}
              </div>
            ) : (
              /* Paginated Spread Mode */
              <div className="w-full h-full flex flex-col items-center justify-between">
                <div className="flex-1 flex items-center justify-center p-2 max-h-[85vh]">
                  <img
                    src={comicImages[comicPageIndex]}
                    alt={`Page ${comicPageIndex + 1}`}
                    className="max-h-full max-w-full object-contain shadow-2xl"
                  />
                </div>
                <div className="h-14 flex items-center gap-4 text-sm text-zinc-300">
                  <button
                    disabled={comicPageIndex === 0}
                    onClick={() => setComicPageIndex((p) => Math.max(0, p - 1))}
                    className="px-4 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 transition font-medium"
                  >
                    Previous
                  </button>
                  <span className="font-mono text-xs">
                    {comicPageIndex + 1} / {comicImages.length}
                  </span>
                  <button
                    disabled={comicPageIndex === comicImages.length - 1}
                    onClick={() => setComicPageIndex((p) => Math.min(comicImages.length - 1, p + 1))}
                    className="px-4 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 transition font-medium"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 4. DOCX Word Document Viewer */}
        {isDocx && !error && (
          <div className="w-full h-full overflow-auto bg-zinc-900 p-4 sm:p-8 flex justify-center">
            <div
              ref={docxContainerRef}
              className="bg-white text-black p-8 max-w-4xl w-full min-h-full shadow-2xl rounded-sm overflow-auto"
            />
          </div>
        )}

        {/* 5. Markdown Viewer */}
        {isMarkdown && !error && !isLoading && (
          <div className="w-full h-full overflow-auto p-6 sm:p-12 flex justify-center">
            <article
              className="prose prose-invert max-w-4xl w-full"
              style={{ fontSize: `${fontSize}px` }}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {textContent}
              </ReactMarkdown>
            </article>
          </div>
        )}

        {/* 6. Plain Text & Source Code Viewer */}
        {isCodeOrText && !error && !isLoading && (
          <div className="w-full h-full overflow-auto p-4 flex justify-center font-mono">
            <pre
              className="w-full max-w-5xl rounded-lg bg-zinc-900/90 border border-zinc-800 p-4 overflow-x-auto text-zinc-200"
              style={{ fontSize: `${fontSize}px`, lineHeight: 1.6 }}
            >
              <code className={`language-${ext === "py" ? "python" : ext === "js" ? "javascript" : ext === "ts" ? "typescript" : ext === "json" ? "json" : ext === "sh" ? "bash" : ext === "css" ? "css" : ext === "html" ? "markup" : ext === "yml" || ext === "yaml" ? "yaml" : ext === "sql" ? "sql" : "none"}`}>
                {textContent}
              </code>
            </pre>
          </div>
        )}

        {/* 7. Spreadsheet Viewer (Excel, CSV, TSV, ODS) */}
        {isSpreadsheet && !error && (
          <SpreadsheetViewer url={url} fileName={fileName} />
        )}

        {/* 8. Presentation Viewer (PowerPoint, PPTX, PPT, etc.) */}
        {isPresentation && !error && (
          <PresentationViewer url={url} fileName={fileName} />
        )}
      </div>
    </div>
  );
};
