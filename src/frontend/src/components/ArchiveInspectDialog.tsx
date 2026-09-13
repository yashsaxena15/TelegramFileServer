import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Folder, File, Archive, Download, Loader2, Sparkles, AlertCircle } from "lucide-react";
import { getApiBaseUrl, fetchWithTimeout } from "@/lib/api";
import { toast } from "sonner";

interface ArchiveFileItem {
  name: string;
  is_dir: boolean;
  size: number;
  compressed_size: number;
  date_time: string;
}

interface ArchiveInspectDialogProps {
  isOpen: boolean;
  onClose: () => void;
  fileId: string;
  fileName: string;
  currentPath: string;
  onExtractSuccess?: () => void;
}

export const ArchiveInspectDialog = ({
  isOpen,
  onClose,
  fileId,
  fileName,
  currentPath,
  onExtractSuccess,
}: ArchiveInspectDialogProps) => {
  const [isLoading, setIsLoading] = useState(true);
  const [isExtracting, setIsExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [files, setFiles] = useState<ArchiveFileItem[]>([]);
  const [totalSize, setTotalSize] = useState<number>(0);

  useEffect(() => {
    if (!isOpen || !fileId) return;

    setIsLoading(true);
    setError(null);

    const inspectArchive = async () => {
      try {
        const baseUrl = getApiBaseUrl();
        const res = await fetchWithTimeout(
          `${baseUrl ? baseUrl : ""}/api/archive/inspect/${encodeURIComponent(fileId)}`
        );
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Failed to inspect archive (${res.status})`);
        }
        const data = await res.json();
        setFiles(data.files || []);
        setTotalSize(data.total_uncompressed_size || 0);
      } catch (err: any) {
        setError(err.message || "Failed to inspect archive contents");
      } finally {
        setIsLoading(false);
      }
    };

    inspectArchive();
  }, [isOpen, fileId]);

  const handleExtract = async () => {
    setIsExtracting(true);
    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetchWithTimeout(
        `${baseUrl ? baseUrl : ""}/api/archive/extract`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            file_id: fileId,
            target_path: currentPath || "/Home",
          }),
        }
      );

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Extraction failed (${res.status})`);
      }

      const data = await res.json();
      toast.success(
        `Extracted ${data.extracted_files} files directly in Telegram cloud!`
      );
      if (onExtractSuccess) onExtractSuccess();
      onClose();
    } catch (err: any) {
      toast.error(err.message || "Cloud extraction failed");
    } finally {
      setIsExtracting(false);
    }
  };

  const formatSize = (bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl bg-zinc-900 border-zinc-800 text-zinc-100 max-h-[85vh] flex flex-col p-6">
        <DialogHeader className="border-b border-zinc-800 pb-4 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-500/10 text-amber-400 rounded-lg">
              <Archive className="w-5 h-5" />
            </div>
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-base font-semibold truncate">
                {fileName}
              </DialogTitle>
              <p className="text-xs text-zinc-400 mt-0.5">
                {isLoading
                  ? "Inspecting archive contents..."
                  : `${files.length} items • Uncompressed: ${formatSize(totalSize)}`}
              </p>
            </div>
          </div>
        </DialogHeader>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto py-4 min-h-[250px] max-h-[50vh]">
          {isLoading ? (
            <div className="h-48 flex flex-col items-center justify-center gap-3 text-zinc-400">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
              <p className="text-sm">Reading archive index from Telegram...</p>
            </div>
          ) : error ? (
            <div className="h-48 flex flex-col items-center justify-center gap-3 text-center p-4">
              <AlertCircle className="w-10 h-10 text-red-400" />
              <p className="text-sm font-medium text-red-300">{error}</p>
            </div>
          ) : files.length === 0 ? (
            <div className="h-48 flex items-center justify-center text-zinc-500 text-sm">
              Archive is empty.
            </div>
          ) : (
            <div className="divide-y divide-zinc-800/60 font-mono text-xs">
              {files.map((item, index) => (
                <div
                  key={index}
                  className="py-2.5 px-3 flex items-center justify-between hover:bg-zinc-800/40 rounded transition"
                >
                  <div className="flex items-center gap-2.5 min-w-0 pr-4">
                    {item.is_dir ? (
                      <Folder className="w-4 h-4 text-amber-400 shrink-0" />
                    ) : (
                      <File className="w-4 h-4 text-zinc-400 shrink-0" />
                    )}
                    <span className="truncate text-zinc-200" title={item.name}>
                      {item.name}
                    </span>
                  </div>
                  <div className="shrink-0 flex items-center gap-4 text-zinc-400">
                    <span>{formatSize(item.size)}</span>
                    <span className="hidden sm:inline text-zinc-500">
                      {item.date_time}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <DialogFooter className="border-t border-zinc-800 pt-4 flex flex-row items-center justify-between gap-2 shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm font-medium transition"
          >
            Close
          </button>
          <button
            disabled={isLoading || Boolean(error) || isExtracting || files.length === 0}
            onClick={handleExtract}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition disabled:opacity-50"
          >
            {isExtracting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Extracting to Cloud...
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                Extract to Cloud
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
