import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  ArrowUpDown,
  ArrowUpCircle,
  ArrowDownCircle,
  CloudDownload,
  Pause,
  Play,
  X,
  RotateCcw,
  Trash2,
  FolderOpen,
  CheckCircle2,
  AlertCircle,
  Clock,
  Folder
} from "lucide-react";
import { useTransferManager } from "@/hooks/useTransferManager";
import { formatBytes } from "@/lib/utils";
import { invoke } from "@tauri-apps/api/core";

export const Transfers = () => {
  const navigate = useNavigate();
  const {
    uploads,
    downloads,
    remoteTransfers,
    stats,
    pauseUpload,
    resumeUpload,
    cancelUpload,
    retryUpload,
    pauseDownload,
    resumeDownload,
    cancelDownload,
    retryDownload,
    cancelRemoteTransfer,
    pauseAll,
    resumeAll,
    cancelAll,
    clearCompleted
  } = useTransferManager();

  const [activeTab, setActiveTab] = useState<"all" | "uploads" | "downloads" | "remote" | "completed">("all");

  const formatSpeed = (bytesPerSec?: number): string => {
    if (!bytesPerSec || bytesPerSec <= 0) return "";
    return `${formatBytes(bytesPerSec)}/s`;
  };

  const formatEta = (seconds?: number): string => {
    if (!seconds || !isFinite(seconds) || seconds <= 0) return "";
    if (seconds > 3600) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    if (seconds > 60) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
    return `${Math.round(seconds)}s`;
  };

  const openDownloadedFile = async (path?: string) => {
    if (!path) return;
    try {
      await invoke("open_file_in_folder", { path });
    } catch (error) {
      console.error("Failed to open file folder:", error);
    }
  };

  // Build unified item list
  const transferItems = [
    ...remoteTransfers.map(r => ({
      ...r,
      type: "remote" as const,
      filesize: r.filesize || 0,
      bytesUploaded: r.transferred_bytes || 0,
      downloaded: r.transferred_bytes || 0,
      file: null,
      startTime: r.created_at
    })),
    ...uploads.map(u => ({ ...u, type: "upload" as const })),
    ...downloads.map(d => ({
      ...d,
      type: "download" as const,
      filesize: d.size || 0,
      bytesUploaded: d.downloaded || 0,
      file: null
    }))
  ];

  // Sort: active/paused items first, then completed/failed by start time
  transferItems.sort((a, b) => {
    const aActive = a.status === "uploading" || a.status === "downloading" || a.status === "uploading_tg" || a.status === "queued" || a.status === "paused";
    const bActive = b.status === "uploading" || b.status === "downloading" || b.status === "uploading_tg" || b.status === "queued" || b.status === "paused";
    if (aActive && !bActive) return -1;
    if (!aActive && bActive) return 1;
    const aTime = (a as any).startTime ? new Date((a as any).startTime).getTime() : 0;
    const bTime = (b as any).startTime ? new Date((b as any).startTime).getTime() : 0;
    return bTime - aTime;
  });

  const filteredItems = transferItems.filter(item => {
    if (activeTab === "uploads") return item.type === "upload";
    if (activeTab === "downloads") return item.type === "download";
    if (activeTab === "remote") return item.type === "remote";
    if (activeTab === "completed") return item.status === "completed";
    return true;
  });

  const hasActiveTransfers = stats.totalActive > 0;
  const hasPausedTransfers = stats.pausedCount > 0;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex-1 overflow-auto bg-gradient-to-br from-blue-50/50 to-indigo-100/50 dark:from-gray-900 dark:to-gray-800/80 py-8 px-4 sm:px-6">
        <div className="max-w-5xl mx-auto">
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
            <div>
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-primary/10 text-primary">
                  <ArrowUpDown className="w-6 h-6" />
                </div>
                <div>
                  <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                    Transfers
                    {stats.totalActive > 0 && (
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-primary text-primary-foreground font-semibold animate-pulse">
                        {stats.totalActive} active
                      </span>
                    )}
                  </h1>
                  <p className="text-xs sm:text-sm text-muted-foreground mt-0.5">
                    Monitor and manage local uploads, downloads, and cloud-to-cloud transfers
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <Button
                variant="outline"
                size="sm"
                onClick={pauseAll}
                disabled={!hasActiveTransfers}
                className="gap-1.5"
                title="Pause all ongoing transfers"
              >
                <Pause className="w-3.5 h-3.5" />
                Pause All
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={resumeAll}
                disabled={!hasPausedTransfers}
                className="gap-1.5"
                title="Resume all paused transfers"
              >
                <Play className="w-3.5 h-3.5" />
                Resume All
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={cancelAll}
                disabled={!hasActiveTransfers && !hasPausedTransfers}
                className="gap-1.5 text-red-600 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950/30"
                title="Cancel all active & paused transfers"
              >
                <X className="w-3.5 h-3.5" />
                Cancel All
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate("/")}
                className="gap-1.5 ml-auto sm:ml-2"
              >
                Back to Files
              </Button>
            </div>
          </div>

          {/* Filter Tabs Card */}
          <Card className="bg-white/90 dark:bg-gray-800/90 border border-border shadow-sm rounded-xl mb-6">
            <div className="p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0">
                <Button
                  variant={activeTab === "all" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setActiveTab("all")}
                  className="rounded-lg text-xs sm:text-sm"
                >
                  All ({transferItems.length})
                </Button>
                <Button
                  variant={activeTab === "remote" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setActiveTab("remote")}
                  className="rounded-lg text-xs sm:text-sm flex items-center gap-1.5 text-purple-600 dark:text-purple-400"
                >
                  <CloudDownload className="w-3.5 h-3.5" />
                  Cloud Leech ({remoteTransfers.length})
                </Button>
                <Button
                  variant={activeTab === "uploads" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setActiveTab("uploads")}
                  className="rounded-lg text-xs sm:text-sm flex items-center gap-1.5"
                >
                  <ArrowUpCircle className="w-3.5 h-3.5 text-blue-500" />
                  Uploads ({uploads.length})
                </Button>
                <Button
                  variant={activeTab === "downloads" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setActiveTab("downloads")}
                  className="rounded-lg text-xs sm:text-sm flex items-center gap-1.5"
                >
                  <ArrowDownCircle className="w-3.5 h-3.5 text-emerald-500" />
                  Downloads ({downloads.length})
                </Button>
                <Button
                  variant={activeTab === "completed" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setActiveTab("completed")}
                  className="rounded-lg text-xs sm:text-sm"
                >
                  Completed ({stats.completedUploads + stats.completedDownloads + (stats as any).completedRemote})
                </Button>
              </div>

              <Button
                variant="ghost"
                size="sm"
                onClick={clearCompleted}
                className="text-xs text-muted-foreground hover:text-foreground shrink-0 self-end sm:self-auto"
              >
                <Trash2 className="w-3.5 h-3.5 mr-1" />
                Clear Completed
              </Button>
            </div>
          </Card>

          {/* Transfers List */}
          {filteredItems.length === 0 ? (
            <Card className="bg-white/80 dark:bg-gray-800/80 border border-border p-12 text-center rounded-xl">
              <ArrowUpDown className="w-12 h-12 text-muted-foreground mx-auto mb-3 opacity-50" />
              <h3 className="text-base font-semibold text-foreground">No transfers found</h3>
              <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto">
                {activeTab === "all"
                  ? "When you initiate cloud downloads, uploads, or downloads, they will show up here live."
                  : `No ${activeTab} items at this moment.`}
              </p>
              <div className="mt-5">
                <Button size="sm" onClick={() => navigate("/")}>
                  Go to Files
                </Button>
              </div>
            </Card>
          ) : (
            <div className="flex flex-col gap-3">
              {filteredItems.map(item => {
                const isRemote = item.type === "remote";
                const isUpload = item.type === "upload";
                const isTransferring = item.status === "uploading" || item.status === "downloading" || item.status === "uploading_tg";
                const isPaused = item.status === "paused";
                const isCompleted = item.status === "completed";
                const isFailed = item.status === "failed";
                const isQueued = item.status === "queued";

                const transferredBytes = item.bytesUploaded || (item.downloaded || 0);
                const totalBytes = item.filesize || (item.size || 0);
                const speedText = formatSpeed(item.speed);
                const etaText = formatEta(item.eta);

                return (
                  <Card
                    key={`${item.type}_${item.id}`}
                    className="bg-white dark:bg-gray-800 border border-border/80 shadow-xs hover:shadow-md transition-all rounded-xl overflow-hidden"
                  >
                    <div className="p-4 flex flex-col gap-3">
                      {/* Top row: Icon, Name, Badges, Actions */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-3 min-w-0 flex-1">
                          <div className={`p-2 rounded-lg shrink-0 ${
                            isRemote ? "bg-purple-100 dark:bg-purple-950/50 text-purple-600 dark:text-purple-400"
                                     : isUpload ? "bg-blue-100 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400"
                                     : "bg-emerald-100 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400"
                          }`}>
                            {isRemote ? (
                              <CloudDownload className="w-5 h-5" />
                            ) : isUpload ? (
                              <ArrowUpCircle className="w-5 h-5" />
                            ) : (
                              <ArrowDownCircle className="w-5 h-5" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-sm text-foreground truncate max-w-xs sm:max-w-md">
                                {item.filename}
                              </span>
                              <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wider ${
                                isRemote ? "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300"
                                         : isUpload ? "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
                                         : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                              }`}>
                                {isRemote ? "Cloud Leech" : isUpload ? "Upload" : "Download"}
                              </span>
                              {/* Status Badge */}
                              <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                                isCompleted ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" :
                                isPaused ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" :
                                isFailed ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" :
                                isQueued ? "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300" :
                                "bg-primary/10 text-primary"
                              }`}>
                                {item.status.toUpperCase()}
                              </span>
                            </div>

                            {/* Phase or Destination info */}
                            <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5 flex-wrap">
                              {isRemote && (item as any).phase && (
                                <span className={`font-medium ${isPaused ? "text-amber-600 dark:text-amber-400" : "text-purple-600 dark:text-purple-400"}`}>
                                  {(item as any).phase}
                                </span>
                              )}
                              {isRemote && (item as any).destination_path && (
                                <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                  <Folder className="w-3 h-3" /> {(item as any).destination_path}
                                </span>
                              )}
                            </div>

                            {/* Secondary stats */}
                            <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1 flex-wrap">
                              <span>
                                {formatBytes(transferredBytes)}
                                {totalBytes > 0 ? ` / ${formatBytes(totalBytes)}` : ""}
                              </span>
                              {isTransferring && speedText && (
                                <span className="font-medium text-foreground">{speedText}</span>
                              )}
                              {isTransferring && etaText && (
                                <span className="flex items-center gap-1">
                                  <Clock className="w-3 h-3" /> ETA: {etaText}
                                </span>
                              )}
                              {item.error && (
                                <span className="text-red-500 font-medium">{item.error}</span>
                              )}
                              {isRemote && (item as any).error_message && (
                                <span className="text-red-500 font-medium">{(item as any).error_message}</span>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Action buttons */}
                        <div className="flex items-center gap-1.5 shrink-0">
                          {!isRemote && isTransferring && (
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground hover:text-foreground"
                              title="Pause"
                              onClick={() => isUpload ? pauseUpload(item.id) : pauseDownload(item.id)}
                            >
                              <Pause className="w-4 h-4" />
                            </Button>
                          )}

                          {!isRemote && isPaused && (
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 text-primary hover:text-primary/80"
                              title="Resume"
                              onClick={() => isUpload ? resumeUpload(item.id) : resumeDownload(item.id)}
                            >
                              <Play className="w-4 h-4" />
                            </Button>
                          )}

                          {(isTransferring || isPaused || isQueued) && (
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
                              title="Cancel"
                              onClick={() => {
                                if (isRemote) {
                                  cancelRemoteTransfer(item.id);
                                } else if (isUpload) {
                                  cancelUpload(item.id);
                                } else {
                                  cancelDownload(item.id);
                                }
                              }}
                            >
                              <X className="w-4 h-4" />
                            </Button>
                          )}

                          {isFailed && !isRemote && (
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 text-blue-600 hover:text-blue-700 hover:bg-blue-50 dark:hover:bg-blue-950/30"
                              title="Retry"
                              onClick={() => isUpload ? retryUpload(item.id) : retryDownload(item as any)}
                            >
                              <RotateCcw className="w-4 h-4" />
                            </Button>
                          )}

                          {isCompleted && !isUpload && !isRemote && (item as any).savePath && (
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 dark:hover:bg-emerald-950/30"
                              title="Show in folder"
                              onClick={() => openDownloadedFile((item as any).savePath)}
                            >
                              <FolderOpen className="w-4 h-4" />
                            </Button>
                          )}
                        </div>
                      </div>

                      {/* Progress Bar */}
                      <Progress
                        value={item.progress}
                        className={`h-1.5 w-full ${
                          isRemote ? "[&>div]:bg-purple-500" :
                          isPaused ? "[&>div]:bg-amber-500" :
                          isCompleted ? "[&>div]:bg-emerald-500" :
                          isFailed ? "[&>div]:bg-red-500" : ""
                        }`}
                      />
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Transfers;
