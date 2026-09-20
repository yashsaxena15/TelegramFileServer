import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTransferManager } from "@/hooks/useTransferManager";
import { formatBytes } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  CloudDownload,
  Pause,
  Play,
  X,
  ChevronDown,
  ChevronUp,
  ExternalLink
} from "lucide-react";

export const TransfersWidget = () => {
  const navigate = useNavigate();
  const {
    uploads,
    downloads,
    remoteTransfers,
    activeUploads,
    activeDownloads,
    activeRemote,
    totalActiveCount,
    stats,
    pauseUpload,
    resumeUpload,
    cancelUpload,
    pauseDownload,
    resumeDownload,
    cancelDownload,
    cancelRemoteTransfer,
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

  // Combine items for widget view (limit to top 6)
  const allItems = [
    ...remoteTransfers.map(r => ({
      ...r,
      type: "remote" as const,
      filesize: r.filesize || 0,
      bytesUploaded: r.transferred_bytes || 0,
      downloaded: r.transferred_bytes || 0
    })),
    ...uploads.map(u => ({ ...u, type: "upload" as const })),
    ...downloads.map(d => ({
      ...d,
      type: "download" as const,
      filesize: d.size || 0,
      bytesUploaded: d.downloaded || 0,
      downloaded: d.downloaded || 0
    }))
  ];

  // Show only if there are active items, or if recently expanded
  const recentItems = allItems
    .filter(i => i.status === "uploading" || i.status === "downloading" || i.status === "uploading_tg" || i.status === "paused" || i.status === "queued")
    .slice(0, 6);

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
          {activeRemote.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-600 dark:text-purple-400 font-medium flex items-center gap-0.5 border border-purple-500/20">
              <CloudDownload className="w-2.5 h-2.5" /> {activeRemote.length}
            </span>
          )}
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
            title="Dismiss widget"
          >
            <X className="w-4 h-4" />
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
              const isRemote = item.type === "remote";
              const isUpload = item.type === "upload";
              const isTransferring = item.status === "uploading" || item.status === "downloading" || item.status === "uploading_tg";
              const isPaused = item.status === "paused";
              const transferred = item.bytesUploaded || (item.downloaded || 0);
              const total = item.filesize || (item.size || 0);

              return (
                <div
                  key={`${item.type}_${item.id}`}
                  className="p-2.5 rounded-lg border border-border/60 bg-muted/15 hover:bg-muted/25 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <div className="flex items-center gap-1.5 min-w-0 flex-1">
                      <span className={`p-1 rounded shrink-0 ${
                        isRemote
                          ? "bg-purple-500/15 text-purple-600 dark:text-purple-400"
                          : isUpload
                          ? "bg-blue-500/15 text-blue-600 dark:text-blue-400"
                          : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                      }`}>
                        {isRemote ? (
                          <CloudDownload className="w-3 h-3" />
                        ) : isUpload ? (
                          <ArrowUp className="w-3 h-3" />
                        ) : (
                          <ArrowDown className="w-3 h-3" />
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-medium text-foreground truncate flex items-center gap-1.5">
                          {item.filename || item.name}
                          {isRemote && (
                            <span className={`text-[9px] px-1 py-0.2 rounded font-normal ${
                              isPaused ? "bg-amber-500/20 text-amber-500" : "bg-purple-500/20 text-purple-400"
                            }`}>
                              {isPaused ? "Paused" : "Cloud Leech"}
                            </span>
                          )}
                        </div>
                        {isRemote && (item as any).phase && (
                          <div className={`text-[10px] truncate ${isPaused ? "text-amber-500 font-medium" : "text-muted-foreground"}`}>
                            {(item as any).phase}
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {!isRemote && isTransferring && (
                        <button
                          className="p-1 text-muted-foreground hover:text-foreground rounded"
                          onClick={() => isUpload ? pauseUpload(item.id) : pauseDownload(item.id)}
                          title="Pause"
                        >
                          <Pause className="w-3.5 h-3.5" />
                        </button>
                      )}
                      {!isRemote && isPaused && (
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
                        onClick={() => {
                          if (isRemote) {
                            cancelRemoteTransfer(item.id);
                          } else if (isUpload) {
                            cancelUpload(item.id);
                          } else {
                            cancelDownload(item.id);
                          }
                        }}
                        title="Cancel"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Progress Bar */}
                  <Progress
                    value={item.progress}
                    className={`h-1 w-full ${isPaused ? "[&>div]:bg-amber-500" : isRemote ? "[&>div]:bg-purple-500" : ""}`}
                  />

                  {/* Stats */}
                  <div className="flex items-center justify-between text-[10px] text-muted-foreground mt-1">
                    <span>
                      {Math.round(item.progress)}% {total > 0 ? `• ${formatBytes(transferred)} of ${formatBytes(total)}` : (transferred > 0 ? `• ${formatBytes(transferred)}` : "")}
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
