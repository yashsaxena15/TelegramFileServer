import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CloudDownload, Folder, CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { FolderPickerModal } from "./FolderPickerModal";

interface RemoteDownloadDialogProps {
  isOpen: boolean;
  onClose: () => void;
  defaultPath?: string;
}

export const RemoteDownloadDialog: React.FC<RemoteDownloadDialogProps> = ({
  isOpen,
  onClose,
  defaultPath = "/Home",
}) => {
  const [url, setUrl] = useState("");
  const [targetPath, setTargetPath] = useState(defaultPath);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync defaultPath when opened
  React.useEffect(() => {
    if (isOpen) {
      setTargetPath(defaultPath || "/Home");
      setError(null);
    }
  }, [isOpen, defaultPath]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanUrl = url.trim();
    if (!cleanUrl) {
      setError("Please enter a valid link.");
      return;
    }

    if (!cleanUrl.startsWith("http://") && !cleanUrl.startsWith("https://")) {
      setError("URL must begin with http:// or https://");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await api.addRemoteTransfer(cleanUrl, targetPath.trim() || "/Home");
      toast.success(res.message || "Cloud Transfer queued successfully!");
      setUrl("");
      window.dispatchEvent(new CustomEvent("remoteTransferAdded"));
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to start remote transfer.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg bg-card text-card-foreground border-border">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <div className="flex items-center gap-2 text-primary">
              <div className="p-2 rounded-xl bg-primary/10 text-primary">
                <CloudDownload className="w-5 h-5" />
              </div>
              <DialogTitle className="text-lg font-bold">
                Remote Cloud Download
              </DialogTitle>
            </div>
            <DialogDescription className="text-xs text-muted-foreground pt-1">
              Transfer files or entire folders from Google Drive and direct links straight to your Telegram cloud. Zero local data or battery used.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4 space-y-4">
            {/* Link Input */}
            <div className="space-y-1.5">
              <Label htmlFor="remote-url" className="text-xs font-semibold">
                Google Drive Link or Direct URL
              </Label>
              <Input
                id="remote-url"
                type="url"
                placeholder="https://drive.google.com/file/d/... or /folders/..."
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  setError(null);
                }}
                disabled={loading}
                autoFocus
                className="text-xs"
              />
              <p className="text-[11px] text-muted-foreground">
                Works with Google Drive files & folders (must be shared as <em>"Anyone with the link can view"</em>) or direct HTTP/HTTPS files.
              </p>
            </div>

            {/* Destination Path */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="dest-path" className="text-xs font-semibold flex items-center gap-1.5">
                  <Folder className="w-3.5 h-3.5 text-primary" />
                  Destination Drive Folder
                </Label>
                <button
                  type="button"
                  onClick={() => setPickerOpen(true)}
                  disabled={loading}
                  className="text-xs text-primary hover:underline font-medium flex items-center gap-1"
                >
                  Browse Folders
                </button>
              </div>

              {/* Clickable Google Drive style Folder Selector Bar */}
              <div
                onClick={() => !loading && setPickerOpen(true)}
                className="flex items-center gap-2.5 p-2.5 rounded-lg border border-input bg-background hover:bg-accent/40 hover:border-primary/50 cursor-pointer transition-all group"
              >
                <div className="p-1.5 rounded-md bg-primary/10 text-primary group-hover:scale-105 transition-transform">
                  <Folder className="w-4 h-4" />
                </div>
                <span className="text-xs font-medium text-foreground flex-1 truncate">
                  {targetPath || "/Home"}
                </span>
                <span className="text-[11px] font-medium text-muted-foreground bg-muted/60 px-2 py-0.5 rounded group-hover:text-foreground">
                  Browse
                </span>
              </div>
            </div>

            {/* Visual Folder Picker Modal */}
            <FolderPickerModal
              isOpen={pickerOpen}
              onClose={() => setPickerOpen(false)}
              currentSelectedPath={targetPath}
              onSelectPath={(selected) => {
                setTargetPath(selected);
              }}
            />

            {/* Error Banner */}
            {error && (
              <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 flex items-start gap-2 text-xs">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span className="leading-relaxed">{error}</span>
              </div>
            )}

            {loading && (
              <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-xs text-blue-400 flex items-start gap-2 animate-pulse">
                <Loader2 className="w-4 h-4 shrink-0 mt-0.5 animate-spin" />
                <div>
                  <div className="font-semibold text-blue-300">Scanning & Queuing Items...</div>
                  <p className="text-[11px] text-blue-300/80 mt-0.5">
                    Scanning subfolders and building the transfer queue. For large folders this may take 30 to 60 seconds. Please keep this dialog open.
                  </p>
                </div>
              </div>
            )}

            {/* Info Callout */}
            <div className="p-3 rounded-lg bg-muted/20 border border-border/60 text-xs text-muted-foreground space-y-1">
              <div className="font-semibold text-foreground flex items-center gap-1.5">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />
                Server-to-Server Autonomous Processing
              </div>
              <p className="text-[11px] leading-relaxed">
                The cloud server downloads and uploads to Telegram in the background. You can safely close this browser or switch off your computer anytime.
              </p>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              disabled={loading}
              className="text-xs"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={loading || !url.trim()}
              className="text-xs gap-1.5"
            >
              {loading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Scanning Google Drive...
                </>
              ) : (
                <>
                  <CloudDownload className="w-3.5 h-3.5" />
                  Start Transfer
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
