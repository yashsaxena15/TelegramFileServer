import { useEffect, useRef } from "react";
import { useIsMobile } from "@/hooks/use-mobile";
import {
  FolderOpen,
  Pencil,
  Trash2,
  Copy,
  Scissors,
  Clipboard,
  Info,
  Download,
  Share2,
  Eye,
  FileText,
  Star,
  RefreshCw,
  Upload,
  RotateCcw,
  Archive,
  Link,
  ShieldCheck,
} from "lucide-react";

interface ContextMenuProps {
  x: number;
  y: number;
  onClose: () => void;
  itemType: "file" | "folder" | "empty";
  itemName: string;
  onOpen?: () => void;
  onCopy: () => void;
  onCut: () => void;
  onPaste?: () => void;
  onDelete: () => void;
  onRename: () => void;
  onNewFolder?: () => void;
  onDownload?: () => void | Promise<void>;
  onUploadFiles?: () => void; // Add upload files callback
  onUploadFolder?: () => void; // Add upload folder callback
  isClipboardPasted?: boolean; // Add prop to track if clipboard item has been pasted
  hasClipboard?: () => boolean; // Add prop to track if there's clipboard content
  disableDelete?: boolean; // Add prop to disable delete option
  onProperties?: () => void; // Add prop to view properties
  onInspectArchive?: () => void; // Peek inside ZIP
  onExtractArchive?: () => void; // Extract ZIP in cloud
  onCompress?: () => void; // Compress to ZIP
  isArchive?: boolean; // Is current item a zip/archive?
  isVideo?: boolean; // Is current item a video?
  onCopyStreamUrl?: () => void; // Copy streaming URL
  selectedCount?: number; // Number of selected items
  isStarred?: boolean;
  onToggleStar?: () => void;
  isTrashMode?: boolean;
  onRestore?: () => void;
  isVaultMode?: boolean;
  onMoveToVault?: () => void;
  onMoveToHome?: () => void;
}

interface MenuItem {
  icon?: any;
  label: string;
  action: string;
  shortcut?: string;
  divider?: boolean;
  danger?: boolean;
  disabled?: boolean;
}

export const ContextMenu = ({
  x,
  y,
  onClose,
  itemType,
  itemName,
  onOpen,
  onCopy,
  onCut,
  onPaste,
  onDelete,
  onRename,
  onNewFolder,
  onDownload,
  onUploadFiles, // Destructure the new prop
  onUploadFolder, // Destructure the new prop
  isClipboardPasted, // Destructure the new prop
  hasClipboard, // Destructure the new prop
  disableDelete = false, // Destructure the new prop with default value
  onProperties,
  onInspectArchive,
  onExtractArchive,
  onCompress,
  isArchive = false,
  isVideo = false,
  onCopyStreamUrl,
  selectedCount = 1,
  isStarred = false,
  onToggleStar,
  isTrashMode = false,
  onRestore,
  isVaultMode = false,
  onMoveToVault,
  onMoveToHome,
}: ContextMenuProps) => {
  const menuRef = useRef<HTMLDivElement>(null);
  const isMobile = useIsMobile();

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose();
      }
    };

    const handleScroll = () => {
      onClose();
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("wheel", handleScroll);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("wheel", handleScroll);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [onClose]);

  const handleAction = async (action: string) => {
    switch (action) {
      case "open":
        onOpen?.();
        onClose();
        break;
      case "copy_stream_url":
        onCopyStreamUrl?.();
        onClose();
        break;
      case "toggle_star":
        onToggleStar?.();
        onClose();
        break;
      case "restore":
        onRestore?.();
        onClose();
        break;
      case "rename":
        onRename();
        onClose();
        break;
      case "copy":
        onCopy();
        onClose();
        break;
      case "cut":
        onCut();
        onClose();
        break;
      case "paste":
        onPaste?.();
        onClose();
        break;
      case "delete":
        onDelete();
        onClose();
        break;
      case "new_folder":
        onNewFolder?.();
        onClose();
        break;
      case "download":
        await onDownload?.();
        onClose();
        break;
      case "upload_files":
        onUploadFiles?.();
        onClose();
        break;
      case "upload_folder":
        onUploadFolder?.();
        onClose();
        break;
      case "properties":
        onProperties?.();
        onClose();
        break;
      case "inspect_archive":
        onInspectArchive?.();
        onClose();
        break;
      case "extract_archive":
        onExtractArchive?.();
        onClose();
        break;
      case "compress":
        onCompress?.();
        onClose();
        break;
      case "move_to_vault":
        onMoveToVault?.();
        onClose();
        break;
      case "move_to_home":
        onMoveToHome?.();
        onClose();
        break;
      default:
        onClose();
    }
  };

  const menuItems: MenuItem[] = isTrashMode
    ? (itemType === "empty"
        ? [
            {
              icon: RefreshCw,
              label: "Refresh",
              action: "refresh",
              shortcut: "F5",
              disabled: true,
            },
          ]
        : [
            {
              icon: RotateCcw,
              label: "Restore",
              action: "restore",
            },
            { divider: true, label: "", action: "" },
            {
              icon: Trash2,
              label: "Delete Forever",
              action: "delete",
              danger: true,
            },
            { divider: true, label: "", action: "" },
            {
              icon: Info,
              label: "Properties",
              action: "properties",
              shortcut: "Alt+Enter",
            },
          ])
    : (itemType === "empty"
        ? [
            // Empty area context menu
            {
              icon: FolderOpen,
              label: "New Folder",
              action: "new_folder",
            },
            { divider: true, label: "", action: "" },
            {
              icon: Clipboard,
              label: "Paste",
              action: "paste",
              shortcut: "Ctrl+V",
            },
            { divider: true, label: "", action: "" },
            {
              icon: RefreshCw,
              label: "Refresh",
              action: "refresh",
              shortcut: "F5",
              disabled: true,
            },
          ]
        : [
            // File/Folder context menu
            {
              icon: Eye,
              label: "Open",
              action: "open",
              shortcut: "Enter",
            },
            ...(isVideo && onCopyStreamUrl
              ? [
                  {
                    icon: Link,
                    label: "Copy Stream URL",
                    action: "copy_stream_url",
                  },
                ]
              : []),
            {
              icon: Star,
              label: isStarred ? "Remove from Starred" : "Add to Starred",
              action: "toggle_star",
            },
            {
              icon: Download,
              label: "Download",
              action: "download",
            },
            ...(isArchive
              ? [
                  { divider: true, label: "", action: "" },
                  {
                    icon: Eye,
                    label: "View Archive",
                    action: "inspect_archive",
                  },
                  {
                    icon: Archive,
                    label: "Extract to Cloud",
                    action: "extract_archive",
                  },
                ]
              : []),
            { divider: true, label: "", action: "" },
            {
              icon: Archive,
              label: selectedCount > 1 ? `Compress to ZIP (${selectedCount})` : "Compress to ZIP",
              action: "compress",
            },
            { divider: true, label: "", action: "" },
            {
              icon: Copy,
              label: selectedCount > 1 ? `Copy (${selectedCount})` : "Copy",
              action: "copy",
              shortcut: "Ctrl+C",
            },
            {
              icon: Scissors,
              label: selectedCount > 1 ? `Cut (${selectedCount})` : "Cut",
              action: "cut",
              shortcut: "Ctrl+X",
            },
            {
              icon: Clipboard,
              label: "Paste",
              action: "paste",
              shortcut: "Ctrl+V",
            },
            { divider: true, label: "", action: "" },
            {
              icon: Pencil,
              label: "Rename",
              action: "rename",
              shortcut: "F2",
            },
            {
              icon: Share2,
              label: "Share",
              action: "share",
              disabled: true,
            },
            ...(isVaultMode
              ? [
                  {
                    icon: FolderOpen,
                    label: selectedCount > 1 ? `Move to Home (${selectedCount})` : "Move to Home",
                    action: "move_to_home",
                  },
                ]
              : [
                  {
                    icon: ShieldCheck,
                    label: selectedCount > 1 ? `Move to Vault 🔒 (${selectedCount})` : "Move to Vault 🔒",
                    action: "move_to_vault",
                  },
                ]),
            { divider: true, label: "", action: "" },
            {
              icon: Trash2,
              label: selectedCount > 1 ? `Move to Trash (${selectedCount})` : "Move to Trash",
              action: "delete",
              shortcut: "Del",
              danger: true,
              disabled: disableDelete,
            },
            { divider: true, label: "", action: "" },
            {
              icon: Info,
              label: "Properties",
              action: "properties",
              shortcut: "Alt+Enter",
            },
          ]);

  if (isMobile) {
    return (
      <>
        {/* Backdrop for mobile */}
        <div
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs transition-opacity"
          onClick={onClose}
        />

        {/* Bottom Sheet Card */}
        <div
          ref={menuRef}
          className="fixed inset-x-0 bottom-0 z-50 bg-background border-t border-border rounded-t-2xl shadow-2xl overflow-hidden pb-6 pt-3 px-4 max-h-[85vh] overflow-y-auto animate-in slide-in-from-bottom duration-200"
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
        >
          {/* Top handle pill */}
          <div className="w-12 h-1 bg-muted-foreground/30 rounded-full mx-auto mb-3" />

          {/* Item Name header if file or folder */}
          {itemName && (
            <div className="text-center pb-3 border-b border-border/60 mb-2">
              <p className="text-sm font-semibold truncate text-foreground px-2">{itemName}</p>
              <p className="text-xs text-muted-foreground capitalize">{itemType}</p>
            </div>
          )}

          <div className="space-y-1">
            {menuItems.map((item, index) => {
              if (item.divider) {
                return (
                  <div
                    key={`divider-${index}`}
                    className="h-px bg-border/50 my-1 mx-1"
                  />
                );
              }

              const Icon = item.icon;
              const isDisabled = item.disabled || (item.action === "paste" && (!hasClipboard || !hasClipboard()));

              return (
                <button
                  key={item.action}
                  onClick={() => !isDisabled && handleAction(item.action)}
                  disabled={isDisabled}
                  className={`w-full flex items-center justify-between px-4 py-3 min-h-[44px] rounded-xl text-left text-sm transition-colors ${
                    isDisabled
                      ? "text-muted-foreground/40 cursor-not-allowed"
                      : item.danger
                      ? "text-destructive hover:bg-destructive/10 active:bg-destructive/20"
                      : "text-foreground hover:bg-accent active:bg-accent/80"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    {Icon && (
                      <Icon
                        className={`w-5 h-5 flex-shrink-0 ${isDisabled ? "opacity-40" : ""}`}
                      />
                    )}
                    <span className="font-medium text-sm">{item.label}</span>
                  </div>
                </button>
              );
            })}
          </div>

          <button
            onClick={onClose}
            className="w-full mt-3 py-2.5 min-h-[44px] rounded-xl border border-border text-center text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent active:bg-accent/80 transition-colors"
          >
            Cancel
          </button>
        </div>
      </>
    );
  }

  // Adjust position to keep menu on screen
  const menuWidth = 280;
  const menuHeight = menuItems.filter((item) => !item.divider).length * 36 + menuItems.filter((item) => item.divider).length * 9;
  const adjustedX = Math.min(x, window.innerWidth - menuWidth - 10);
  const adjustedY = Math.min(y, window.innerHeight - menuHeight - 10);

  return (
    <>
      {/* Backdrop for better visibility */}
      <div
        className="fixed inset-0 z-40"
        style={{ background: "transparent" }}
        onClick={onClose}
      />

      <div
        ref={menuRef}
        className="fixed z-50 bg-background/80 backdrop-blur-md border border-border/50 rounded-xl shadow-2xl overflow-hidden"
        style={{
          left: `${adjustedX}px`,
          top: `${adjustedY}px`,
          width: `${menuWidth}px`,
          animation: "context-menu-in 0.1s ease-out",
        }}
      >
        <div className="py-1">
          {menuItems.map((item, index) => {
            if (item.divider) {
              return (
                <div
                  key={`divider-${index}`}
                  className="h-px bg-border/50 my-1 mx-1"
                />
              );
            }

            const Icon = item.icon;
            const isDisabled = item.disabled || (item.action === "paste" && (!hasClipboard || !hasClipboard()));
            
            return (
              <button
                key={item.action}
                onClick={() => !isDisabled && handleAction(item.action)}
                disabled={isDisabled}
                className={`w-full flex items-center justify-between px-3 py-2 text-left text-sm transition-colors group ${
                  isDisabled
                    ? "text-muted-foreground/50 cursor-not-allowed"
                    : item.danger
                    ? "text-foreground hover:bg-destructive hover:text-destructive-foreground"
                    : "text-foreground hover:bg-accent hover:text-accent-foreground"
                  }`}
              >
                <div className="flex items-center gap-3">
                  {Icon && (
                    <Icon
                      className={`w-4 h-4 flex-shrink-0 ${isDisabled ? "opacity-40" : ""
                        }`}
                    />
                  )}
                  <span className="font-normal">{item.label}</span>
                </div>
                {item.shortcut && (
                  <span
                    className={`text-xs font-mono ${isDisabled
                      ? "text-muted-foreground/30"
                      : "text-muted-foreground group-hover:text-accent-foreground/70"
                      }`}
                  >
                    {item.shortcut}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <style>{`
        @keyframes context-menu-in {
          from {
            opacity: 0;
            transform: scale(0.95);
          }
          to {
            opacity: 1;
            transform: scale(1);
          }
        }
      `}</style>
    </>
  );
};