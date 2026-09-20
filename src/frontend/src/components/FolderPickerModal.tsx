import React, { useState, useEffect } from "react";
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
import {
  Folder,
  FolderOpen,
  FolderPlus,
  ChevronRight,
  ArrowLeft,
  Check,
  Loader2,
  ShieldCheck,
  Inbox,
  HardDrive
} from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

interface FolderPickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentSelectedPath: string;
  onSelectPath: (path: string) => void;
}

interface SubfolderItem {
  name: string;
  path: string;
}

export const FolderPickerModal: React.FC<FolderPickerModalProps> = ({
  isOpen,
  onClose,
  currentSelectedPath,
  onSelectPath,
}) => {
  // Path being browsed inside the picker modal
  const [navPath, setNavPath] = useState<string>("/Home");
  const [folders, setFolders] = useState<SubfolderItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [isCreatingFolder, setIsCreatingFolder] = useState<boolean>(false);
  const [newFolderName, setNewFolderName] = useState<string>("");
  const [creatingLoading, setCreatingLoading] = useState<boolean>(false);

  // Initialize navPath from currentSelectedPath when opened
  useEffect(() => {
    if (isOpen) {
      const initial = (currentSelectedPath && currentSelectedPath.trim()) ? currentSelectedPath.trim() : "/Home";
      setNavPath(initial);
      setIsCreatingFolder(false);
      setNewFolderName("");
    }
  }, [isOpen, currentSelectedPath]);

  // Load subfolders whenever navPath changes
  const loadSubfolders = async (targetPath: string) => {
    setLoading(true);
    try {
      // Clean path for API call
      const clean = targetPath.startsWith("/") ? targetPath : `/${targetPath}`;
      const res = await api.fetchFiles(clean);
      const subfolders: SubfolderItem[] = (res.files || [])
        .filter((f: any) => f.file_type === "folder" || f.type === "folder")
        .map((f: any) => ({
          name: f.file_name || f.name,
          path: f.file_path ? `${f.file_path}/${f.file_name || f.name}`.replace(/\/+/g, "/") : `${clean}/${f.file_name || f.name}`.replace(/\/+/g, "/"),
        }));
      setFolders(subfolders);
    } catch (err) {
      console.error("Failed to fetch folders for picker:", err);
      setFolders([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadSubfolders(navPath);
    }
  }, [isOpen, navPath]);

  // Handle Root section switches
  const handleRootSwitch = (root: string) => {
    setNavPath(root);
  };

  // Navigate deeper into a subfolder
  const handleEnterSubfolder = (folder: SubfolderItem) => {
    const nextPath = `${navPath.replace(/\/+$/, "")}/${folder.name}`.replace(/\/+/g, "/");
    setNavPath(nextPath);
  };

  // Navigate up one level
  const handleGoUp = () => {
    const parts = navPath.split("/").filter(Boolean);
    if (parts.length <= 1) {
      // Already at root level (/Home, /Vault, etc.)
      return;
    }
    parts.pop();
    setNavPath(`/${parts.join("/")}`);
  };

  // Breadcrumbs click
  const handleBreadcrumbClick = (index: number, parts: string[]) => {
    const next = "/" + parts.slice(0, index + 1).join("/");
    setNavPath(next);
  };

  // Create new folder inside the currently viewed directory
  const handleCreateFolder = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanName = newFolderName.trim();
    if (!cleanName) return;

    setCreatingLoading(true);
    try {
      await api.createFolder(cleanName, navPath);
      toast.success(`Created folder "${cleanName}"`);
      setNewFolderName("");
      setIsCreatingFolder(false);
      await loadSubfolders(navPath);
    } catch (err: any) {
      toast.error(err.message || "Failed to create folder");
    } finally {
      setCreatingLoading(false);
    }
  };

  const handleConfirmSelect = () => {
    onSelectPath(navPath);
    onClose();
  };

  // Split path for breadcrumb navigation
  const pathParts = navPath.split("/").filter(Boolean);
  const canGoUp = pathParts.length > 1;

  // Active root tab detection
  const currentRoot = pathParts[0] || "Home";

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl max-h-[85vh] flex flex-col p-0 gap-0 bg-card text-card-foreground border-border overflow-hidden">
        {/* Header */}
        <DialogHeader className="p-5 pb-3 border-b border-border/60">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-primary/10 text-primary">
              <FolderOpen className="w-5 h-5" />
            </div>
            <div>
              <DialogTitle className="text-base font-bold">
                Select Destination Folder
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground mt-0.5">
                Browse through your cloud storage and select a destination
              </DialogDescription>
            </div>
          </div>

          {/* Root Quick Switchers */}
          <div className="flex items-center gap-1.5 pt-3">
            <button
              type="button"
              onClick={() => handleRootSwitch("/Home")}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                currentRoot === "Home"
                  ? "bg-primary text-primary-foreground shadow-xs"
                  : "bg-muted/40 hover:bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              <HardDrive className="w-3.5 h-3.5" />
              Home
            </button>
            <button
              type="button"
              onClick={() => handleRootSwitch("/Vault")}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                currentRoot === "Vault"
                  ? "bg-purple-600 text-white shadow-xs"
                  : "bg-muted/40 hover:bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              Private Vault
            </button>
            <button
              type="button"
              onClick={() => handleRootSwitch("/inbox")}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                currentRoot === "inbox"
                  ? "bg-blue-600 text-white shadow-xs"
                  : "bg-muted/40 hover:bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              <Inbox className="w-3.5 h-3.5" />
              Telegram Inbox
            </button>
          </div>
        </DialogHeader>

        {/* Breadcrumb Navigation & Action Bar */}
        <div className="px-5 py-2.5 bg-muted/20 border-b border-border/50 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1 min-w-0 overflow-x-auto text-xs py-0.5 custom-scrollbar">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={!canGoUp}
              onClick={handleGoUp}
              className="h-7 w-7 rounded-md shrink-0 text-muted-foreground hover:text-foreground"
              title="Go to parent folder"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
            </Button>

            <div className="flex items-center gap-1 shrink-0 font-medium">
              {pathParts.map((part, idx) => {
                const isLast = idx === pathParts.length - 1;
                return (
                  <React.Fragment key={idx}>
                    {idx > 0 && <ChevronRight className="w-3 h-3 text-muted-foreground/50 shrink-0" />}
                    <button
                      type="button"
                      onClick={() => handleBreadcrumbClick(idx, pathParts)}
                      className={`px-1.5 py-0.5 rounded transition-colors truncate max-w-[120px] ${
                        isLast
                          ? "text-primary font-semibold bg-primary/10 cursor-default"
                          : "text-muted-foreground hover:text-foreground hover:underline"
                      }`}
                    >
                      {part}
                    </button>
                  </React.Fragment>
                );
              })}
            </div>
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setIsCreatingFolder(!isCreatingFolder)}
            className="h-7 px-2 text-xs gap-1 shrink-0 border-border/70 hover:bg-accent"
          >
            <FolderPlus className="w-3.5 h-3.5 text-primary" />
            <span className="hidden sm:inline">New Folder</span>
          </Button>
        </div>

        {/* Inline Create Folder Bar */}
        {isCreatingFolder && (
          <form onSubmit={handleCreateFolder} className="p-3 bg-muted/40 border-b border-border/60 flex items-center gap-2">
            <Folder className="w-4 h-4 text-primary shrink-0 ml-1" />
            <Input
              type="text"
              placeholder="New folder name..."
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              disabled={creatingLoading}
              autoFocus
              className="h-8 text-xs flex-1 bg-background"
            />
            <Button
              type="submit"
              size="sm"
              disabled={creatingLoading || !newFolderName.trim()}
              className="h-8 text-xs px-3"
            >
              {creatingLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Create"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setIsCreatingFolder(false);
                setNewFolderName("");
              }}
              className="h-8 text-xs px-2"
            >
              Cancel
            </Button>
          </form>
        )}

        {/* Folder List Explorer */}
        <div className="flex-1 overflow-y-auto p-4 min-h-[220px] max-h-[340px] custom-scrollbar">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-44 gap-2 text-muted-foreground">
              <Loader2 className="w-6 h-6 animate-spin text-primary" />
              <span className="text-xs">Loading folders...</span>
            </div>
          ) : folders.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-44 text-center px-4">
              <div className="p-3 rounded-full bg-muted/30 text-muted-foreground mb-2">
                <FolderOpen className="w-7 h-7 stroke-[1.5]" />
              </div>
              <p className="text-xs font-semibold text-foreground">No subfolders here</p>
              <p className="text-[11px] text-muted-foreground mt-0.5 max-w-xs">
                You can save directly into this directory, or click "+ New Folder" above to create one.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {folders.map((folder) => (
                <div
                  key={folder.name}
                  onClick={() => handleEnterSubfolder(folder)}
                  className="flex items-center justify-between p-2.5 rounded-xl border border-border/60 hover:border-primary/40 bg-background hover:bg-accent/60 cursor-pointer transition-all group"
                >
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <div className="p-2 rounded-lg bg-primary/10 text-primary shrink-0 group-hover:scale-105 transition-transform">
                      <Folder className="w-4 h-4" />
                    </div>
                    <span className="text-xs font-medium text-foreground truncate">
                      {folder.name}
                    </span>
                  </div>
                  <ChevronRight className="w-4 h-4 text-muted-foreground/40 group-hover:text-primary transition-colors shrink-0 ml-1" />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <DialogFooter className="p-4 bg-muted/10 border-t border-border/60 flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <span className="text-xs text-muted-foreground shrink-0 font-medium">Selected:</span>
            <span className="text-xs font-semibold text-primary truncate bg-primary/10 px-2 py-1 rounded-md border border-primary/20">
              {navPath}
            </span>
          </div>

          <div className="flex items-center gap-2 justify-end shrink-0">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onClose}
              className="text-xs h-9 px-3"
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleConfirmSelect}
              className="text-xs h-9 px-4 gap-1.5 bg-primary text-primary-foreground shadow-sm"
            >
              <Check className="w-3.5 h-3.5" />
              Select This Folder
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
