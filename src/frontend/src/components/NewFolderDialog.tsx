import { useState, useEffect, useRef } from "react";
import { toast } from "sonner";
import { FolderPlus, AlertCircle } from "lucide-react";

interface NewFolderDialogProps {
  open: boolean;
  currentPath: string;
  onClose: () => void;
  onConfirm: (folderName: string) => void;
}

const MAX_FOLDER_NAME_LENGTH = 60;
const MAX_FOLDER_DEPTH = 100;
const FORBIDDEN_CHARS_REGEX = /[/\\:*?"<>|\x00-\x1f]/;

export const NewFolderDialog = ({ open, currentPath, onClose, onConfirm }: NewFolderDialogProps) => {
  const [folderName, setFolderName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Calculate current subfolder depth relative to root (/Home)
  const segments = currentPath ? currentPath.split("/").filter((p) => p && p !== "Home") : [];
  const currentDepth = segments.length;
  const isMaxDepthReached = currentDepth >= MAX_FOLDER_DEPTH;

  useEffect(() => {
    if (open && inputRef.current && !isMaxDepthReached) {
      inputRef.current.focus();
    }
  }, [open, isMaxDepthReached]);

  const hasForbiddenChars = FORBIDDEN_CHARS_REGEX.test(folderName);
  const isNameEmpty = !folderName.trim();
  const isReservedName = folderName.trim() === "." || folderName.trim() === "..";
  const isValid = !isMaxDepthReached && !isNameEmpty && !hasForbiddenChars && !isReservedName && folderName.length <= MAX_FOLDER_NAME_LENGTH;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (isMaxDepthReached) {
      toast.error(`Maximum folder depth limit (${MAX_FOLDER_DEPTH} levels) reached.`);
      return;
    }

    const trimmed = folderName.trim();
    if (!trimmed) {
      toast.error("Folder name cannot be empty");
      return;
    }

    if (trimmed.length > MAX_FOLDER_NAME_LENGTH) {
      toast.error(`Folder name cannot exceed ${MAX_FOLDER_NAME_LENGTH} characters`);
      return;
    }

    if (FORBIDDEN_CHARS_REGEX.test(trimmed)) {
      toast.error('Folder name cannot contain: / \\ : * ? " < > |');
      return;
    }

    if (trimmed === "." || trimmed === "..") {
      toast.error("Folder name cannot be '.' or '..'");
      return;
    }

    onConfirm(trimmed);
    setFolderName("");
  };

  const handleClose = () => {
    setFolderName("");
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      handleClose();
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-center z-50 p-4">
      <div 
        className="bg-background border border-border rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in-0 zoom-in-95 duration-150"
        onKeyDown={handleKeyDown}
      >
        <div className="p-6">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-9 h-9 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 flex items-center justify-center">
              <FolderPlus className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">Create New Folder</h2>
              <p className="text-xs text-muted-foreground">
                Depth: <span className="font-medium text-foreground">{currentDepth}</span> / {MAX_FOLDER_DEPTH} levels
              </p>
            </div>
          </div>

          {isMaxDepthReached ? (
            <div className="p-3 mb-4 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>
                Maximum folder depth limit of <strong>{MAX_FOLDER_DEPTH} levels</strong> reached. You cannot create subfolders inside this folder.
              </span>
            </div>
          ) : null}

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <div className="flex justify-between items-center mb-1.5">
                <label htmlFor="folderName" className="text-xs font-medium text-foreground">
                  Folder Name
                </label>
                <span className={`text-[11px] font-mono ${
                  folderName.length > MAX_FOLDER_NAME_LENGTH - 10 
                    ? "text-amber-500 font-semibold" 
                    : "text-muted-foreground"
                }`}>
                  {folderName.length}/{MAX_FOLDER_NAME_LENGTH}
                </span>
              </div>

              <input
                ref={inputRef}
                id="folderName"
                type="text"
                disabled={isMaxDepthReached}
                maxLength={MAX_FOLDER_NAME_LENGTH}
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
                className={`w-full px-3 py-2 text-sm border rounded-lg focus:outline-none transition-colors ${
                  hasForbiddenChars || isReservedName
                    ? "border-destructive bg-destructive/5 text-foreground focus:ring-1 focus:ring-destructive"
                    : "border-input bg-background text-foreground focus:ring-2 focus:ring-primary focus:border-transparent"
                } disabled:opacity-50 disabled:cursor-not-allowed`}
                placeholder="Enter folder name"
              />

              {hasForbiddenChars && (
                <p className="text-xs text-destructive mt-1.5 flex items-center gap-1">
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                  Cannot contain: / \ : * ? &quot; &lt; &gt; |
                </p>
              )}

              {isReservedName && (
                <p className="text-xs text-destructive mt-1.5 flex items-center gap-1">
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                  Folder name cannot be &quot;.&quot; or &quot;..&quot;
                </p>
              )}
            </div>

            <div className="flex justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={handleClose}
                className="px-3.5 py-1.5 text-xs font-medium text-foreground bg-secondary hover:bg-secondary/80 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!isValid}
                className="px-4 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/40 disabled:cursor-not-allowed rounded-lg shadow-xs transition-colors"
              >
                Create Folder
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};