import { useState } from "react";
import { FileItem, getFileIcon } from "@/components/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Folder,
  FileText,
  Copy,
  Check,
  Download,
  Calendar,
  HardDrive,
  FolderTree,
  Hash,
  Link as LinkIcon,
  Info,
} from "lucide-react";
import { getApiBaseUrl } from "@/lib/api";
import { toast } from "sonner";

interface PropertiesDialogProps {
  open: boolean;
  item: FileItem | null;
  currentPath?: string[];
  currentApiPath?: string;
  onClose: () => void;
  onDownload?: (item: FileItem) => void;
}

export const PropertiesDialog = ({
  open,
  item,
  currentPath,
  currentApiPath,
  onClose,
  onDownload,
}: PropertiesDialogProps) => {
  const [copiedField, setCopiedField] = useState<string | null>(null);

  if (!item) return null;

  const baseUrl = getApiBaseUrl();
  const token = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : "";
  const directUrl = `${baseUrl ? baseUrl : ""}/dl/${encodeURIComponent(item.name)}${tokenParam}`;

  const copyToClipboard = async (text: string, fieldName: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(fieldName);
      toast.success(`Copied ${fieldName} to clipboard`);
      setTimeout(() => setCopiedField(null), 2000);
    } catch (err) {
      toast.error("Failed to copy to clipboard");
    }
  };

  const formatFileSize = (bytes?: number): string => {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const formatDateTime = (dateStr?: string): string => {
    if (!dateStr) return "Unknown";
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return dateStr;
      return d.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "medium",
      });
    } catch {
      return dateStr;
    }
  };

  const getReadableType = (): string => {
    if (item.type === "folder") return "File Folder";
    const ext = item.name.includes(".") ? item.name.split(".").pop()?.toUpperCase() : "";
    const type = item.fileType ? item.fileType.charAt(0).toUpperCase() + item.fileType.slice(1) : "File";
    return ext ? `${ext} ${type} (.${ext.toLowerCase()})` : type;
  };

  const getLocationPath = (): string => {
    if (item.file_path) return item.file_path;
    if (currentApiPath) return currentApiPath;
    if (currentPath && currentPath.length > 0) return `/${currentPath.join("/")}`;
    return "/Home";
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="bg-background/95 backdrop-blur-md border border-border rounded-xl shadow-2xl max-w-md w-full p-5 sm:p-6 overflow-hidden">
        <DialogHeader className="pb-3 border-b border-border/60">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-muted/70 flex items-center justify-center text-2xl flex-shrink-0 border border-border/40 shadow-xs">
              {item.type === "folder" ? "📁" : getFileIcon(item)}
            </div>
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-base font-semibold text-foreground truncate" title={item.name}>
                {item.name}
              </DialogTitle>
              <p className="text-xs text-muted-foreground mt-0.5">{getReadableType()}</p>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4 py-3 max-h-[60vh] overflow-y-auto pr-1 text-xs sm:text-sm">
          {/* General Section */}
          <div className="space-y-2.5">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">General</h4>

            <div className="grid grid-cols-3 gap-2 py-1.5 border-b border-border/40">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <Info className="w-3.5 h-3.5" /> Type:
              </span>
              <span className="col-span-2 font-medium text-foreground break-words">{getReadableType()}</span>
            </div>

            <div className="grid grid-cols-3 gap-2 py-1.5 border-b border-border/40">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <FolderTree className="w-3.5 h-3.5" /> Location:
              </span>
              <span className="col-span-2 font-medium text-foreground break-all">{getLocationPath()}</span>
            </div>

            {item.type !== "folder" && (
              <div className="grid grid-cols-3 gap-2 py-1.5 border-b border-border/40">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <HardDrive className="w-3.5 h-3.5" /> Size:
                </span>
                <span className="col-span-2 font-medium text-foreground">
                  {formatFileSize(item.size)}
                  {item.size ? ` (${item.size.toLocaleString()} bytes)` : ""}
                </span>
              </div>
            )}

            <div className="grid grid-cols-3 gap-2 py-1.5 border-b border-border/40">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5" /> Modified:
              </span>
              <span className="col-span-2 font-medium text-foreground">{formatDateTime(item.modified)}</span>
            </div>
          </div>

          {/* Telegram / Cloud Storage Section */}
          {item.type !== "folder" && (
            <div className="space-y-2.5 pt-1">
              <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Cloud & Stream Info
              </h4>

              {item.file_unique_id && (
                <div className="space-y-1 py-1.5 border-b border-border/40">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
                      <Hash className="w-3.5 h-3.5" /> Unique ID:
                    </span>
                    <button
                      type="button"
                      onClick={() => copyToClipboard(item.file_unique_id!, "Unique ID")}
                      className="p-1 text-xs text-muted-foreground hover:text-foreground rounded transition-colors flex items-center gap-1"
                      title="Copy ID"
                    >
                      {copiedField === "Unique ID" ? (
                        <Check className="w-3.5 h-3.5 text-emerald-500" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                  <p className="font-mono text-[11px] text-foreground bg-muted/50 p-1.5 rounded border border-border/40 break-all select-all">
                    {item.file_unique_id}
                  </p>
                </div>
              )}

              {/* Direct Download / Streaming Link */}
              <div className="space-y-1 py-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
                    <LinkIcon className="w-3.5 h-3.5" /> Direct Download Link:
                  </span>
                  <button
                    type="button"
                    onClick={() => copyToClipboard(directUrl, "Direct Link")}
                    className="p-1 text-xs text-muted-foreground hover:text-foreground rounded transition-colors flex items-center gap-1"
                    title="Copy Link"
                  >
                    {copiedField === "Direct Link" ? (
                      <Check className="w-3.5 h-3.5 text-emerald-500" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
                <p className="font-mono text-[11px] text-foreground bg-muted/50 p-1.5 rounded border border-border/40 break-all select-all truncate">
                  {directUrl}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 pt-3 border-t border-border/60">
          {item.type !== "folder" && onDownload && (
            <button
              type="button"
              onClick={() => {
                onDownload(item);
                onClose();
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-xs"
            >
              <Download className="w-3.5 h-3.5" />
              Download
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-1.5 text-xs font-medium rounded-lg bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-colors"
          >
            Close
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
