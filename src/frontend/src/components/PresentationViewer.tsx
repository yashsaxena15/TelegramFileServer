import { useEffect, useState, useRef } from "react";
import { ReactPptxViewer, setWasmSource, type ViewerMode, type PptxViewerController } from "@extend-ai/react-pptx";
import wasmUrl from "@extend-ai/react-pptx/pptx_wasm_bg.wasm?url";
import "@extend-ai/react-pptx/styles.css";
import { Loader2, AlertCircle, Presentation, Scroll, PanelLeft, RotateCcw } from "lucide-react";

try {
  setWasmSource(wasmUrl);
} catch (e) {
  // Already initialized or fallback
}

interface PresentationViewerProps {
  url: string;
  fileName: string;
}

export const PresentationViewer = ({ url, fileName }: PresentationViewerProps) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewerMode>("continuous");
  const [showThumbnails, setShowThumbnails] = useState(true);
  const controllerRef = useRef<PptxViewerController | null>(null);

  useEffect(() => {
    let isMounted = true;
    let createdUrl: string | null = null;
    setIsLoading(true);
    setError(null);

    const fetchFile = async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`Failed to load presentation (${response.status})`);
        }
        const blob = await response.blob();
        if (!isMounted) return;
        createdUrl = URL.createObjectURL(blob);
        setBlobUrl(createdUrl);
      } catch (err: any) {
        if (!isMounted) return;
        setError(err.message || "Failed to load presentation file");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };

    fetchFile();

    return () => {
      isMounted = false;
      if (createdUrl) {
        URL.revokeObjectURL(createdUrl);
      }
    };
  }, [url]);

  if (isLoading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center min-h-[400px] gap-3 text-muted-foreground">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <p className="text-sm font-medium">Loading presentation...</p>
        <p className="text-xs opacity-60">Parsing slides and layouts</p>
      </div>
    );
  }

  if (error || !blobUrl) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center min-h-[400px] gap-3 text-center p-6">
        <AlertCircle className="w-10 h-10 text-destructive" />
        <p className="text-base font-semibold text-foreground">Failed to display presentation</p>
        <p className="text-sm text-muted-foreground max-w-md">{error}</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-zinc-950 text-foreground relative">
      {/* Top Custom Toolbar */}
      <div className="px-4 py-2 border-b border-zinc-800 bg-zinc-900/70 flex items-center justify-between gap-3 shrink-0 select-none">
        {/* Left: Format badge */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-orange-500/10 text-orange-400 border border-orange-500/20 text-xs font-medium">
            <Presentation className="w-3.5 h-3.5" />
            <span>PowerPoint Deck</span>
          </div>
        </div>

        {/* Right: View mode controls */}
        <div className="flex items-center gap-2">
          {/* Thumbnails Sidebar Toggle */}
          <button
            onClick={() => setShowThumbnails(!showThumbnails)}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded transition ${
              showThumbnails
                ? "bg-zinc-800 text-white font-medium"
                : "text-zinc-400 hover:text-white hover:bg-zinc-800/60"
            }`}
            title="Toggle slide thumbnails rail"
          >
            <PanelLeft className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Thumbnails</span>
          </button>

          {/* Mode Switch: Continuous Scroll vs Single Slide */}
          <div className="flex items-center bg-zinc-800/80 rounded p-0.5 border border-zinc-700/50">
            <button
              onClick={() => setMode("continuous")}
              className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded transition ${
                mode === "continuous"
                  ? "bg-primary text-primary-foreground font-semibold"
                  : "text-zinc-400 hover:text-white"
              }`}
              title="Continuous vertical scroll mode"
            >
              <Scroll className="w-3.5 h-3.5" />
              <span>Scroll</span>
            </button>
            <button
              onClick={() => setMode("slide")}
              className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded transition ${
                mode === "slide"
                  ? "bg-primary text-primary-foreground font-semibold"
                  : "text-zinc-400 hover:text-white"
              }`}
              title="Slide-by-slide flip mode"
            >
              <Presentation className="w-3.5 h-3.5" />
              <span>Slide</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Presentation Surface */}
      <div className="flex-1 w-full h-full overflow-hidden relative pptx-viewer-container">
        <ReactPptxViewer
          ref={(controller) => {
            controllerRef.current = controller;
          }}
          source={blobUrl}
          mode={mode}
          showThumbnails={showThumbnails}
          showToolbar={true}
          showSlideLabels={true}
          virtualization={true}
          height="100%"
          width="100%"
          onError={(err) => {
            console.error("Presentation render error:", err);
            setError(err.message || "Failed to render presentation");
          }}
        />
      </div>

      {/* Dark mode CSS overrides for @extend-ai/react-pptx */}
      <style>{`
        .pptx-viewer-container .rpv-root {
          --rpv-ink: #f4f4f5;
          --rpv-paper: #09090b;
          --rpv-panel: #18181b;
          --rpv-rule: #27272a;
          --rpv-accent: #f97316;
          border: none;
          background: #09090b;
          color: #f4f4f5;
          height: 100%;
          display: flex;
          flex-direction: column;
        }
        .pptx-viewer-container .rpv-toolbar {
          background: #18181b;
          border-bottom: 1px solid #27272a;
          color: #f4f4f5;
        }
        .pptx-viewer-container .rpv-toolbar button:hover:not(:disabled) {
          background: #27272a;
        }
        .pptx-viewer-container .rpv-filmstrip {
          background: #121215;
          border-right: 1px solid #27272a;
        }
        .pptx-viewer-container .rpv-thumbnail__canvas {
          background: #18181b;
          border-color: #27272a;
        }
        .pptx-viewer-container .rpv-thumbnail__number {
          color: #a1a1aa;
        }
        .pptx-viewer-container .rpv-stage {
          background: #09090b;
        }
      `}</style>
    </div>
  );
};
