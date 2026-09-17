import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Pause,
  Play,
  X,
  RotateCcw,
  ChevronDown,
  ChevronUp,
  ExternalLink
} from "lucide-react";
import { useTransferManager } from "@/hooks/useTransferManager";
import { formatBytes } from "@/lib/utils";

export const TransfersWidget = () => {
  const navigate = useNavigate();
  const {
    uploads,
    downloads,
    activeUploads,
    activeDownloads,
    totalActiveCount,
    stats,
    pauseUpload,
    resumeUpload,
    cancelUpload,
    pauseDownload,
    resumeDownload,
    cancelDownload,
    pauseAll,
    resumeAll
  } = useTransferManager();

  const [isExpanded, setIsExpanded] = useState(false);
  const [isDismissed, setIsDismissed] = useState(false);

  // Auto-expand when a new transfer begins
  useEffect(() => {
    if (totalActiveCount > 0) {
      setIsDismissed(false);
    }
  }, [totalActiveCount]);

  // Combine items for widget view (limit to top 5)
  const allItems = [
    ...uploads.map(u => ({ ...u, type: "upload" as const })),
    ...downloads.map(d => ({
      ...d,
      type: "download" as const,
      filesize: d.size || 0,
      bytesUploaded: d.downloaded || 0
    }))
  ];

  // Show only if there are active items, or if recently expanded
  const recentItems = allItems
    .filter(i => i.status === "uploading" || i.status === "downloading" || i.status === "paused" || i.status === "queued")
    .slice(0, 5);

  if (recentItems.length === 0 && !isExpanded) {
    return null;
  }

  if (isDismissed) {
    return null;
  }

  const formatSpeed = (bytesPerSec?: number): string => {
    if (!bytesPerSec || bytesPerSec <= 0) return "";
    return `${formatBytes(bytesPerSec)}/s`;
  };

  return (
    <div className="fixed bottom-4 right-4 z-40 w-[calc(100vw-2rem)] sm:w-96 shadow-2xl rounded-xl border border-border bg-card text-card-foreground overflow-hidden transition-all duration-300 ease-in-out">
      {/* Header Bar */}
      <div className="px-4 py-2.5 bg-card hover:bg-muted/15 border-b border-border flex items-center justify-between transition-colors">
        <div 
          className="flex items-center gap-2 cursor-pointer select-none flex-1"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <div className="p-1.5 rounded-lg bg-primary/10 text-primary">
            <ArrowUpDown className="w-4 h-4" />
          </div>
          <span className="font-semibold text-xs text-foreground">
            Transfers {totalActiveCount > 0 ? `(${totalActiveCount} active)` : ""}
          </span>
          {activeUploads.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-600 dark:text-blue-400 font-medium flex items-center gap-0.5 border border-blue-500/20">
              <ArrowUp className="w-2.5 h-2.5" /> {activeUploads.length}
            </span>
          )}
          {activeDownloads.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-0.5 border border-emerald-500/20">
              <ArrowDown className="w-2.5 h-2.5" /> {activeDownloads.length}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {totalActiveCount > 0 && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-foreground"
              onClick={pauseAll}
              title="Pause All"
            >
              <Pause className="w-3.5 h-3.5" />
            </Button>
          )}
          {stats.pausedCount > 0 && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-primary hover:text-primary/80"
              onClick={resumeAll}
              title="Resume All"
            >
              <Play className="w-3.5 h-3.5" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? "Collapse" : "Expand"}
          >
            {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
            onClick={() => setIsDismissed(true)}
            title="Close"
          >
            <X className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      {/* Expanded Transfers List */}
      {isExpanded && (
        <div className="max-h-72 overflow-y-auto p-3 flex flex-col gap-2.5 custom-scrollbar">
          {recentItems.length === 0 ? (
            <p className="text-center text-xs text-muted-foreground py-4">No active transfers</p>
          ) : (
            recentItems.map(item => {
              const isUpload = item.type === "upload";
              const isTransferring = item.status === "uploading" || item.status === "downloading";
              const isPaused = item.status === "paused";
              const transferred = isUpload ? item.bytesUploaded : (item.downloaded || 0);
              const total = item.filesize || (item.size || 0);

              return (
                <div
                  key={`${item.type}_${item.id}`}
                  className="p-2.5 rounded-lg border border-border/60 bg-muted/15 hover:bg-muted/25 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <div className="flex items-center gap-1.5 min-w-0 flex-1">
                      <span className={`p-1 rounded shrink-0 ${
                        isUpload ? "bg-blue-500/15 text-blue-600 dark:text-blue-400" : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                      }`}>
                        {isUpload ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                      </span>
                      <span className="text-xs font-medium text-foreground truncate">
                        {item.filename}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {isTransferring && (
                        <button
                          className="p-1 text-muted-foreground hover:text-foreground rounded"
                          onClick={() => isUpload ? pauseUpload(item.id) : pauseDownload(item.id)}
                          title="Pause"
                        >
                          <Pause className="w-3.5 h-3.5" />
                        </button>
                      )}
                      {isPaused && (
                        <button
                          className="p-1 text-primary hover:text-primary/80 rounded"
                          onClick={() => isUpload ? resumeUpload(item.id) : resumeDownload(item.id)}
                          title="Resume"
                        >
                          <Play className="w-3.5 h-3.5" />
                        </button>
                      )}
                      <button
                        className="p-1 text-red-500 hover:text-red-600 rounded"
                        onClick={() => isUpload ? cancelUpload(item.id) : cancelDownload(item.id)}
                        title="Cancel"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Progress Bar */}
                  <Progress
                    value={item.progress}
                    className={`h-1 w-full ${isPaused ? "[&>div]:bg-amber-500" : ""}`}
                  />

                  {/* Stats */}
                  <div className="flex items-center justify-between text-[10px] text-muted-foreground mt-1">
                    <span>
                      {Math.round(item.progress)}% • {formatBytes(transferred)} of {formatBytes(total)}
                    </span>
                    {isTransferring && item.speed ? (
                      <span>{formatSpeed(item.speed)}</span>
                    ) : (
                      <span className="capitalize">{item.status}</span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Footer Link to /transfers */}
      {isExpanded && (
        <div className="p-2 bg-card border-t border-border flex items-center justify-center">
          <Button
            variant="ghost"
            size="sm"
            className="w-full text-xs gap-1.5 h-7 text-primary hover:text-primary"
            onClick={() => navigate("/transfers")}
          >
            Open Transfers Center
            <ExternalLink className="w-3 h-3" />
          </Button>
        </div>
      )}
    </div>
  );
};
