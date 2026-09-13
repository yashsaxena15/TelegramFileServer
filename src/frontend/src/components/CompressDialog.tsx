import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Archive, Loader2, Sparkles } from "lucide-react";
import { getApiBaseUrl, fetchWithTimeout } from "@/lib/api";
import { toast } from "sonner";

interface CompressDialogProps {
  isOpen: boolean;
  onClose: () => void;
  selectedItemIds: string[];
  selectedItemNames: string[];
  currentPath: string;
  onCompressSuccess?: () => void;
}

export const CompressDialog = ({
  isOpen,
  onClose,
  selectedItemIds,
  selectedItemNames,
  currentPath,
  onCompressSuccess,
}: CompressDialogProps) => {
  const defaultName =
    selectedItemNames.length === 1
      ? `${selectedItemNames[0].replace(/\.[^/.]+$/, "")}.zip`
      : "Archive.zip";

  const [zipName, setZipName] = useState(defaultName);
  const [isCompressing, setIsCompressing] = useState(false);

  const handleCompress = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!zipName.trim()) return;

    setIsCompressing(true);
    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetchWithTimeout(
        `${baseUrl ? baseUrl : ""}/api/archive/compress`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            item_ids: selectedItemIds,
            destination_path: currentPath || "/Home",
            zip_name: zipName.trim(),
          }),
        }
      );

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Compression failed (${res.status})`);
      }

      const data = await res.json();
      toast.success(`Created archive '${data.file_name}' directly in Telegram cloud!`);
      if (onCompressSuccess) onCompressSuccess();
      onClose();
    } catch (err: any) {
      toast.error(err.message || "Cloud compression failed");
    } finally {
      setIsCompressing(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md bg-zinc-900 border-zinc-800 text-zinc-100 p-6">
        <form onSubmit={handleCompress}>
          <DialogHeader className="border-b border-zinc-800 pb-4">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-primary/10 text-primary rounded-lg">
                <Archive className="w-5 h-5" />
              </div>
              <div>
                <DialogTitle className="text-base font-semibold">
                  Compress to Cloud ZIP
                </DialogTitle>
                <p className="text-xs text-zinc-400 mt-0.5">
                  {selectedItemIds.length} item(s) selected for compression
                </p>
              </div>
            </div>
          </DialogHeader>

          <div className="py-5 space-y-3">
            <label className="text-xs text-zinc-300 font-medium block">
              Archive File Name
            </label>
            <input
              type="text"
              required
              value={zipName}
              onChange={(e) => setZipName(e.target.value)}
              placeholder="e.g. MyFiles.zip"
              className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-md text-sm text-zinc-100 focus:outline-none focus:border-primary font-mono"
            />
            <p className="text-xs text-zinc-500">
              Files will be packed directly on the server into your Telegram cloud drive.
            </p>
          </div>

          <DialogFooter className="border-t border-zinc-800 pt-4 flex flex-row items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isCompressing}
              className="px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm font-medium transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isCompressing || !zipName.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition disabled:opacity-50"
            >
              {isCompressing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Compressing...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  Create Archive
                </>
              )}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
