import React, { useState, useRef } from "react";
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
import {
  CloudDownload,
  Folder,
  CheckCircle,
  AlertCircle,
  Loader2,
  Magnet,
  Link2,
  FileUp,
  FileText,
  X
} from "lucide-react";
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
  const [mode, setMode] = useState<"url" | "torrent">("url");
  const [url, setUrl] = useState("");
  const [torrentFile, setTorrentFile] = useState<File | null>(null);
  const [targetPath, setTargetPath] = useState(defaultPath);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Sync defaultPath when opened
  React.useEffect(() => {
    if (isOpen) {
      setTargetPath(defaultPath || "/Home");
      setError(null);
      setTorrentFile(null);
      setUrl("");
    }
  }, [isOpen, defaultPath]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (!file.name.toLowerCase().endsWith(".torrent")) {
        setError("Please select a valid .torrent file.");
        return;
      }
      setTorrentFile(file);
      setError(null);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (!file.name.toLowerCase().endsWith(".torrent")) {
        setError("Please drop a valid .torrent file.");
        return;
      }
      setTorrentFile(file);
      setError(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (mode === "url") {
      const cleanUrl = url.trim();
      if (!cleanUrl) {
        setError("Please enter a valid link or magnet URL.");
        return;
      }

      const isHttp = cleanUrl.startsWith("http://") || cleanUrl.startsWith("https://");
      const isMagnet = cleanUrl.startsWith("magnet:?xt=");

      if (!isHttp && !isMagnet) {
        setError("URL must begin with http://, https://, or magnet:?xt=");
        return;
      }

      setLoading(true);
      try {
        const res = await api.addRemoteTransfer(cleanUrl, targetPath.trim() || "/Home");
        toast.success(res.message || "Cloud transfer queued successfully!");
        setUrl("");
        window.dispatchEvent(new CustomEvent("remoteTransferAdded"));
        onClose();
      } catch (err: any) {
        setError(err.message || "Failed to start remote transfer.");
      } finally {
        setLoading(false);
      }
    } else {
      // Torrent file mode
      if (!torrentFile) {
        setError("Please select a .torrent file to upload.");
        return;
      }

      setLoading(true);
      try {
        const res = await api.uploadTorrentFile(torrentFile, targetPath.trim() || "/Home");
        toast.success(res.message || "Torrent leech queued successfully!");
        setTorrentFile(null);
        window.dispatchEvent(new CustomEvent("remoteTransferAdded"));
        onClose();
      } catch (err: any) {
        setError(err.message || "Failed to start torrent transfer.");
      } finally {
        setLoading(false);
      }
    }
  };

  const isMagnetLink = url.trim().startsWith("magnet:?xt=");

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
                Cloud Leech & Remote Transfer
              </DialogTitle>
            </div>
            <DialogDescription className="text-xs text-muted-foreground pt-1">
              Direct cloud-to-cloud downloads for Google Drive, Magnet links, Torrent files, and direct links. Saves directly to your Telegram storage.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4 space-y-4">
            {/* Mode Switcher Tabs */}
            <div className="grid grid-cols-2 p-1 bg-muted/60 rounded-lg text-xs font-semibold">
              <button
                type="button"
                onClick={() => {
                  setMode("url");
                  setError(null);
                }}
                className={`flex items-center justify-center gap-2 py-1.5 px-3 rounded-md transition-all ${
                  mode === "url"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Link2 className="w-3.5 h-3.5 text-primary" />
                <span>Link / Magnet</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setMode("torrent");
                  setError(null);
                }}
                className={`flex items-center justify-center gap-2 py-1.5 px-3 rounded-md transition-all ${
                  mode === "torrent"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <FileUp className="w-3.5 h-3.5 text-purple-500" />
                <span>.torrent File</span>
              </button>
            </div>

            {/* Mode 1: URL / Magnet Input */}
            {mode === "url" ? (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="remote-url" className="text-xs font-semibold">
                    Google Drive, Direct Link, or Magnet URL
                  </Label>
                  {isMagnetLink && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-600 dark:text-purple-400 font-semibold flex items-center gap-1 border border-purple-500/20">
                      <Magnet className="w-2.5 h-2.5" /> Magnet Detected
                    </span>
                  )}
                </div>
                <Input
                  id="remote-url"
                  type="text"
                  placeholder="https://drive.google.com/... or magnet:?xt=urn:btih:..."
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    setError(null);
                  }}
                  disabled={loading}
                  autoFocus
                  className="text-xs font-mono"
                />
                <p className="text-[11px] text-muted-foreground">
                  Works with Google Drive files & folders, BitTorrent Magnet links, or direct HTTP/HTTPS file URLs.
                </p>
              </div>
            ) : (
              /* Mode 2: .torrent File Dropzone */
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">
                  Upload .torrent File
                </Label>
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  accept=".torrent"
                  className="hidden"
                />

                {!torrentFile ? (
                  <div
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                    className="border-2 border-dashed border-input hover:border-primary/60 bg-muted/20 hover:bg-muted/40 p-5 rounded-xl cursor-pointer text-center transition-all group"
                  >
                    <div className="flex flex-col items-center gap-2">
                      <div className="p-2.5 rounded-full bg-primary/10 text-primary group-hover:scale-110 transition-transform">
                        <FileUp className="w-5 h-5" />
                      </div>
                      <div className="text-xs font-medium text-foreground">
                        Click to browse or drag & drop .torrent file
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        All files and folders in the torrent will be downloaded and saved to your Telegram drive.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-between p-3 rounded-lg border border-purple-500/30 bg-purple-500/10">
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <div className="p-2 rounded-lg bg-purple-500/20 text-purple-500 shrink-0">
                        <FileText className="w-4 h-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold text-foreground truncate">
                          {torrentFile.name}
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          {(torrentFile.size / 1024).toFixed(1)} KB
                        </div>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-red-500"
                      onClick={() => {
                        setTorrentFile(null);
                        if (fileInputRef.current) fileInputRef.current.value = "";
                      }}
                    >
                      <X className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* Destination Path Selector */}
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

            {/* Loading Indicator */}
            {loading && (
              <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-xs text-blue-400 flex items-start gap-2 animate-pulse">
                <Loader2 className="w-4 h-4 shrink-0 mt-0.5 animate-spin" />
                <div>
                  <div className="font-semibold text-blue-300">
                    {mode === "url" && isMagnetLink
                      ? "Resolving Magnet & Connecting..."
                      : mode === "torrent"
                      ? "Queuing Torrent Leech..."
                      : "Scanning & Queuing Items..."}
                  </div>
                  <p className="text-[11px] text-blue-300/80 mt-0.5">
                    Building the server transfer queue. Nested folder structure will be strictly preserved.
                  </p>
                </div>
              </div>
            )}

            {/* Info Callout */}
            <div className="p-3 rounded-lg bg-muted/20 border border-border/60 text-xs text-muted-foreground space-y-1">
              <div className="font-semibold text-foreground flex items-center gap-1.5">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />
                Folder Hierarchy & Pipelined Uploads
              </div>
              <p className="text-[11px] leading-relaxed">
                Multi-file torrents and folders preserve their exact nested hierarchy in your selected drive folder. All downloads upload in 1.95 GB chunks to Telegram without filling server disk.
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
              disabled={loading || (mode === "url" ? !url.trim() : !torrentFile)}
              className="text-xs gap-1.5"
            >
              {loading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Processing...
                </>
              ) : isMagnetLink ? (
                <>
                  <Magnet className="w-3.5 h-3.5" />
                  Leech Magnet
                </>
              ) : mode === "torrent" ? (
                <>
                  <FileUp className="w-3.5 h-3.5" />
                  Leech Torrent
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
