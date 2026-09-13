import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Download, FileArchive, Folder, Layers, CheckCircle } from "lucide-react";
import { useState } from "react";

export interface FolderPartInfo {
  part_index: number;
  name: string;
  size: number;
  files_count: number;
  download_url: string;
}

export interface FolderDownloadInfo {
  folder_name: string;
  full_path: string;
  total_files: number;
  total_size: number;
  total_parts: number;
  parts: FolderPartInfo[];
}

interface FolderDownloadDialogProps {
  open: boolean;
  info: FolderDownloadInfo | null;
  onClose: () => void;
  onDownloadPart: (part: FolderPartInfo) => void;
  onDownloadAll: (parts: FolderPartInfo[]) => void;
}

export const FolderDownloadDialog = ({
  open,
  info,
  onClose,
  onDownloadPart,
  onDownloadAll,
}: FolderDownloadDialogProps) => {
  const [downloadedParts, setDownloadedParts] = useState<Set<number>>(new Set());

  if (!info) return null;

  const formatFileSize = (bytes?: number): string => {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const handleSingleDownload = (part: FolderPartInfo) => {
    setDownloadedParts(prev => new Set(prev).add(part.part_index));
    onDownloadPart(part);
  };

  const handleAllDownload = () => {
    const allIndices = info.parts.map(p => p.part_index);
    setDownloadedParts(new Set(allIndices));
    onDownloadAll(info.parts);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="bg-background/95 backdrop-blur-md border border-border rounded-xl shadow-2xl max-w-lg w-full p-5 sm:p-6 overflow-hidden">
        <DialogHeader className="pb-3 border-b border-border/60">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 flex items-center justify-center text-2xl flex-shrink-0 border border-blue-500/20 shadow-xs">
              <Folder className="w-6 h-6" />
            </div>
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-base font-semibold text-foreground truncate" title={info.folder_name}>
                Download &ldquo;{info.folder_name}&rdquo;
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2">
                <span>{info.total_files} {info.total_files === 1 ? "file" : "files"}</span>
                <span>•</span>
                <span className="font-medium text-foreground">{formatFileSize(info.total_size)}</span>
                <span>•</span>
                <span className="text-blue-600 dark:text-blue-400 font-medium">
                  {info.total_parts} {info.total_parts === 1 ? "part" : "zip parts"}
                </span>
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-3 py-3 text-xs sm:text-sm">
          <div className="p-3 bg-muted/40 rounded-lg border border-border/50 text-xs text-muted-foreground leading-relaxed flex items-start gap-2.5">
            <Layers className="w-4 h-4 text-blue-500 shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-foreground">Multi-part Zip Archive (Google Drive style)</p>
              <p className="mt-0.5">
                This folder exceeds 2 GB. To ensure standard compatibility and reliable downloading, it has been divided into {info.total_parts} independent zip archives (max 2 GB each).
              </p>
            </div>
          </div>

          <div className="space-y-2 max-h-[45vh] overflow-y-auto pr-1">
            {info.parts.map((part) => {
              const isQueued = downloadedParts.has(part.part_index);
              return (
                <div
                  key={part.part_index}
                  className="flex items-center justify-between p-3 rounded-lg border border-border/60 bg-card hover:bg-accent/40 transition-colors gap-3"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-9 h-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                      <FileArchive className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium text-xs sm:text-sm text-foreground truncate" title={part.name}>
                        {part.name}
                      </p>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        {formatFileSize(part.size)} • {part.files_count} {part.files_count === 1 ? "file" : "files"}
                      </p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleSingleDownload(part)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors shadow-xs shrink-0 ${
                      isQueued
                        ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                        : "bg-primary text-primary-foreground hover:bg-primary/90"
                    }`}
                  >
                    {isQueued ? (
                      <>
                        <CheckCircle className="w-3.5 h-3.5" />
                        Queued
                      </>
                    ) : (
                      <>
                        <Download className="w-3.5 h-3.5" />
                        Download
                      </>
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 pt-3 border-t border-border/60">
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-1.5 text-xs font-medium rounded-lg bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-colors"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleAllDownload}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm font-semibold"
          >
            <Download className="w-4 h-4" />
            Download All Parts ({info.total_parts})
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
