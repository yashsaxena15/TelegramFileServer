import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useParams, useNavigate } from "react-router-dom";
import {
  FileItem,
  SortField,
  SortOrder,
  FileTypeFilter,
  SizeFilter,
  DateFilter,
  isVideoItem,
  isPhotoItem,
  isAudioItem,
  isArchiveItem,
  isDocumentItem,
} from "@/components/types";
import { ContextMenu } from "./ContextMenu";
import { useFiles } from "@/hooks/useFiles";
import { useFileOperations } from "@/hooks/useFileOperations";
import { toast } from "sonner";
import { copyStreamUrl } from "@/lib/utils";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { FileGrid } from "./FileGrid";
import { DeleteDialog } from "./DeleteDialog";
import { NewFolderDialog } from "./NewFolderDialog";
import { RenameInput } from "./RenameInput";
import { StorageAnalyticsContent } from "./StorageAnalyticsContent";
import { ProfileContent } from "./ProfileContent";
import { SettingsContent } from "./SettingsContent";
import { UserManagementContent } from "./UserManagementContent";
import Transfers from "@/pages/Transfers";
import { getApiBaseUrl, resetApiBaseUrl, updateApiBaseUrl, fetchWithTimeout, api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import logger from "@/lib/logger";
import { X as XIcon, Trash2, RotateCcw, AlertCircle } from "lucide-react";
import { downloadManager } from "@/lib/downloadManager";
import { motion, AnimatePresence } from "framer-motion";
import { useError } from "@/contexts/ErrorHandlerContext"; // Import the error context
import { FolderDownloadDialog, FolderDownloadInfo, FolderPartInfo } from "./FolderDownloadDialog";
import { WebDAVMountDialog } from "./WebDAVMountDialog";

export const FileExplorer = () => {
  const location = useLocation();
  const navigate = useNavigate(); // Add navigate hook
  const { path } = useParams();
  const { showError } = useError(); // Use the error context

  // Initialize currentPath from URL or localStorage or default to ["Home"]
  const [currentPath, setCurrentPath] = useState<string[]>(() => {
    // First check if we have a path in the URL
    if (location.pathname && location.pathname !== "/") {
      // Split the path and filter out empty segments
      const pathSegments = location.pathname.split('/').filter(segment => segment.length > 0);
      if (pathSegments.length > 0) {
        // Decode each segment to handle URL encoding (e.g., %20 for spaces)
        const decodedSegments = pathSegments.map(segment => decodeURIComponent(segment));
        // If the first segment is not "Home", add it
        if (decodedSegments[0] !== "Home") {
          return ["Home", ...decodedSegments];
        }
        return decodedSegments;
      }
    }
    
    // Fallback to localStorage or default
    const savedPath = localStorage.getItem('fileExplorerPath');
    if (savedPath) {
      try {
        const parsedPath = JSON.parse(savedPath);
        if (Array.isArray(parsedPath)) {
          return parsedPath;
        }
      } catch (e) {
        logger.error('Failed to parse saved path', e);
      }
    }
    return ["Home"];
  });
  
  const [showProfile, setShowProfile] = useState(() => window.location.pathname === '/profile');
  const [showSettings, setShowSettings] = useState(() => window.location.pathname === '/settings');
  const [showUserManagement, setShowUserManagement] = useState(() => window.location.pathname === '/users');
  const [showStorageAnalytics, setShowStorageAnalytics] = useState(() => window.location.pathname === '/storage');
  const [showTransfers, setShowTransfers] = useState(() => window.location.pathname === '/transfers' || window.location.pathname === '/downloads');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [emptyTrashDialogOpen, setEmptyTrashDialogOpen] = useState(false); // State to confirm empty trash
  const [isEmptyingTrash, setIsEmptyingTrash] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [selectedFilter, setSelectedFilter] = useState<string>("all");
  const [newFolderDialogOpen, setNewFolderDialogOpen] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState<{ item: FileItem; index: number } | null>(null);
  const [renamingItem, setRenamingItem] = useState<{ item: FileItem; index: number } | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; itemType: "file" | "folder" | "empty"; itemName: string; item?: FileItem; index?: number } | null>(null);
  const [folderDownloadInfo, setFolderDownloadInfo] = useState<FolderDownloadInfo | null>(null);
  const [showWebDAVDialog, setShowWebDAVDialog] = useState(false);
  const queryClient = useQueryClient();

  // Listen for showWebDAVMount custom events
  useEffect(() => {
    const handleOpenWebDAV = () => setShowWebDAVDialog(true);
    window.addEventListener('showWebDAVMount', handleOpenWebDAV);
    return () => window.removeEventListener('showWebDAVMount', handleOpenWebDAV);
  }, []);

  // Save currentPath to localStorage whenever it changes
  useEffect(() => {
    localStorage.setItem('fileExplorerPath', JSON.stringify(currentPath));
  }, [currentPath]);

  // Update browser history when currentPath changes
  useEffect(() => {
    // Update the browser history with the new path
    const pathString = currentPath.length === 1 && currentPath[0] === "Home" 
      ? "/" 
      : "/" + currentPath.slice(1).map(segment => encodeURIComponent(segment)).join('/');
    
    // Use replaceState for the initial load to avoid creating extra history entries
    if (window.history.state === null) {
      window.history.replaceState({ path: currentPath }, '', pathString);
    } else {
      window.history.pushState({ path: currentPath }, '', pathString);
    }
  }, [currentPath]);

  // Handle browser back/forward buttons
  useEffect(() => {
    const handlePopState = (event: PopStateEvent) => {
      if (event.state && event.state.path) {
        setCurrentPath(event.state.path);
      } else {
        // Parse the path from the URL
        const pathSegments = window.location.pathname.split('/').filter(segment => segment.length > 0);
        if (pathSegments.length === 0) {
          setCurrentPath(["Home"]);
        } else {
          // Decode each segment to handle URL encoding (e.g., %20 for spaces)
          const decodedSegments = pathSegments.map(segment => decodeURIComponent(segment));
          setCurrentPath(decodedSegments);
        }
      }
      
      // Also check if we should show profile, settings, user management, storage analytics, or downloads based on the new location
      const p = window.location.pathname;
      setShowProfile(p === '/profile');
      setShowSettings(p === '/settings');
      setShowUserManagement(p === '/users');
      setShowStorageAnalytics(p === '/storage');
      setShowTransfers(p === '/transfers' || p === '/downloads');
    };
    
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  // Sync view states whenever location.pathname changes
  useEffect(() => {
    const p = location.pathname;
    setShowProfile(p === '/profile');
    setShowSettings(p === '/settings');
    setShowUserManagement(p === '/users');
    setShowStorageAnalytics(p === '/storage');
    setShowTransfers(p === '/transfers' || p === '/downloads');
  }, [location.pathname]);

  // Log when the component mounts
  useEffect(() => {
    logger.info("FileExplorer component mounted", { currentPath, location: window.location.pathname });
  }, []);

  // Refresh files when component mounts and user is at Home path
  useEffect(() => {
    if (currentPath.length === 1 && currentPath[0] === "Home") {
      // Trigger a refresh to ensure default folders are visible
      refetch();
    }
  }, []); // Empty dependency array means this runs once on mount

  // Check current route and show appropriate content on mount
  useEffect(() => {
    if (location.pathname === '/profile') {
      setShowProfile(true);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
    } else if (location.pathname === '/settings') {
      setShowSettings(true);
      setShowProfile(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
    } else if (location.pathname === '/users') {
      setShowUserManagement(true);
      setShowProfile(false);
      setShowSettings(false);
      setShowStorageAnalytics(false);
    } else if (location.pathname === '/storage') {
      setShowStorageAnalytics(true);
      setShowProfile(false);
      setShowSettings(false);
      setShowUserManagement(false);
    } else {
      setShowProfile(false);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
    }
  }, [location.pathname]);

  // Listen for showProfile event
  useEffect(() => {
    const handleShowProfile = () => {
      setShowProfile(true);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
    };

    window.addEventListener('showProfile', handleShowProfile);
    return () => {
      window.removeEventListener('showProfile', handleShowProfile);
    };
  }, []);

  // Listen for showSettings event
  useEffect(() => {
    const handleShowSettings = () => {
      setShowSettings(true);
      setShowProfile(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
    };

    window.addEventListener('showSettings', handleShowSettings);
    return () => {
      window.removeEventListener('showSettings', handleShowSettings);
    };
  }, []);

  // Listen for showUsers event
  useEffect(() => {
    const handleShowUsers = () => {
      setShowUserManagement(true);
      setShowProfile(false);
      setShowSettings(false);
      setShowStorageAnalytics(false);
    };

    window.addEventListener('showUsers', handleShowUsers);
    return () => {
      window.removeEventListener('showUsers', handleShowUsers);
    };
  }, []);

  // Listen for showStorageAnalytics event
  useEffect(() => {
    const handleShowStorageAnalytics = () => {
      setShowStorageAnalytics(true);
      setShowProfile(false);
      setShowSettings(false);
      setShowUserManagement(false);
    };

    window.addEventListener('showStorageAnalytics', handleShowStorageAnalytics);
    return () => {
      window.removeEventListener('showStorageAnalytics', handleShowStorageAnalytics);
    };
  }, []);

  // Listen for showTransfers and showDownloads events
  useEffect(() => {
    const handleShowTransfers = () => {
      setShowTransfers(true);
      setShowProfile(false);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
    };

    window.addEventListener('showTransfers', handleShowTransfers);
    window.addEventListener('showDownloads', handleShowTransfers);
    return () => {
      window.removeEventListener('showTransfers', handleShowTransfers);
      window.removeEventListener('showDownloads', handleShowTransfers);
    };
  }, []);

  // Listen for showFiles event (when closing profile/settings/user management/storage/transfers)
  useEffect(() => {
    const handleShowFiles = () => {
      setShowProfile(false);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
      setShowTransfers(false);
      
      // Reset currentPath to Home when returning to file view
      setCurrentPath(["Home"]);
      
      // Close navigation sidebar when returning to file view
      const event = new CustomEvent('toggleNavigationSidebar', { detail: { action: 'close' } });
      window.dispatchEvent(event);
    };

    window.addEventListener('showFiles', handleShowFiles);
    return () => {
      window.removeEventListener('showFiles', handleShowFiles);
    };
  }, []);

  // Current folder name (last part of currentPath)
  const currentFolder = currentPath[currentPath.length - 1] || "Home";

  const isTrashMode = selectedFilter === "trash" || currentFolder === "Trash";
  const isStarredMode = selectedFilter === "starred" || currentFolder === "Starred";
  const isInboxMode = selectedFilter === "inbox" || currentFolder === "Telegram Inbox";

  // Convert currentPath to API path format
  const currentApiPath = isTrashMode
    ? "/trash"
    : isStarredMode
    ? "/starred"
    : isInboxMode
    ? "/inbox"
    : currentPath.length === 1 && currentPath[0] === "Home"
    ? "/Home"
    : `/${currentPath.join('/')}`;
  const { files, isLoading, isError, error, refetch } = useFiles(currentApiPath);
  const { clipboard, cutItems, copyItem, cutItem, clearClipboard, hasClipboard, isClipboardPasted, pasteItem, moveItem } = useFileOperations();

  // Sort state
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");
  const [foldersFirst, setFoldersFirst] = useState<boolean>(true);

  // Filter state
  const [typeFilter, setTypeFilter] = useState<FileTypeFilter>("all");
  const [sizeFilter, setSizeFilter] = useState<SizeFilter>("all");
  const [dateFilter, setDateFilter] = useState<DateFilter>("all");

  // Base items in current folder/section
  const baseItems = useMemo((): FileItem[] => {
    if (!Array.isArray(files)) return [];
    if (currentFolder === "Home" && selectedFilter === "all") {
      return files.filter(
        (f) => f.type === "folder" || f.file_path === "/Home" || f.file_path === "/"
      );
    }
    return files;
  }, [files, currentFolder, selectedFilter]);

  // Compute category counts for quick filter chips
  const typeCounts = useMemo((): Record<FileTypeFilter, number> => {
    const counts: Record<FileTypeFilter, number> = {
      all: baseItems.length,
      folder: 0,
      video: 0,
      document: 0,
      photo: 0,
      audio: 0,
      archive: 0,
    };

    for (const item of baseItems) {
      if (!item) continue;
      if (item.type === "folder") {
        counts.folder += 1;
      } else if (isVideoItem(item)) {
        counts.video += 1;
      } else if (isPhotoItem(item)) {
        counts.photo += 1;
      } else if (isAudioItem(item)) {
        counts.audio += 1;
      } else if (isArchiveItem(item)) {
        counts.archive += 1;
      } else if (isDocumentItem(item)) {
        counts.document += 1;
      }
    }

    return counts;
  }, [baseItems]);

  // Filtered and sorted items
  const filteredItems = useMemo((): FileItem[] => {
    let result = [...baseItems];

    // 1. Search filter
    if (searchQuery && searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter((item) => (item?.name || "").toLowerCase().includes(q));
    }

    // 2. Type filter
    if (typeFilter !== "all") {
      result = result.filter((item) => {
        if (!item) return false;
        if (typeFilter === "folder") return item.type === "folder";
        if (item.type === "folder") return false;
        if (typeFilter === "video") return isVideoItem(item);
        if (typeFilter === "photo") return isPhotoItem(item);
        if (typeFilter === "audio") return isAudioItem(item);
        if (typeFilter === "archive") return isArchiveItem(item);
        if (typeFilter === "document") return isDocumentItem(item);
        return true;
      });
    }

    // 3. Size filter
    if (sizeFilter !== "all") {
      result = result.filter((item) => {
        if (!item) return false;
        if (item.type === "folder") return true;
        const size = typeof item.size === "number" ? item.size : 0;
        if (sizeFilter === "small") return size < 10 * 1024 * 1024;
        if (sizeFilter === "medium") return size >= 10 * 1024 * 1024 && size < 100 * 1024 * 1024;
        if (sizeFilter === "large") return size >= 100 * 1024 * 1024 && size < 1024 * 1024 * 1024;
        if (sizeFilter === "huge") return size >= 1024 * 1024 * 1024;
        return true;
      });
    }

    // 4. Date filter
    if (dateFilter !== "all") {
      const now = Date.now();
      const oneDay = 24 * 60 * 60 * 1000;
      result = result.filter((item) => {
        if (!item) return false;
        const dateStr = item.trashed_at || item.modified;
        if (!dateStr) return true;
        const time = new Date(dateStr).getTime();
        if (isNaN(time)) return true;
        const diff = now - time;
        if (dateFilter === "today") return diff <= oneDay;
        if (dateFilter === "week") return diff <= 7 * oneDay;
        if (dateFilter === "month") return diff <= 30 * oneDay;
        return true;
      });
    }

    // 5. Sorting
    result.sort((a, b) => {
      if (!a || !b) return 0;
      if (foldersFirst && a.type !== b.type) {
        return a.type === "folder" ? -1 : 1;
      }

      let comparison = 0;
      if (sortField === "name") {
        const nameA = a.name || "";
        const nameB = b.name || "";
        comparison = nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: "base" });
      } else if (sortField === "size") {
        const sizeA = typeof a.size === "number" ? a.size : 0;
        const sizeB = typeof b.size === "number" ? b.size : 0;
        comparison = sizeA - sizeB;
      } else if (sortField === "date") {
        const getDateScore = (item: FileItem): number => {
          if (item.trashed_at) {
            const t = new Date(item.trashed_at).getTime();
            if (!isNaN(t)) return t;
          }
          if (item.modified) {
            const t = new Date(item.modified).getTime();
            if (!isNaN(t)) return t;
          }
          if (typeof item.message_id === "number") {
            return item.message_id;
          }
          return 0;
        };
        comparison = getDateScore(a) - getDateScore(b);
      }

      return sortOrder === "asc" ? comparison : -comparison;
    });

    return result;
  }, [baseItems, searchQuery, typeFilter, sizeFilter, dateFilter, sortField, sortOrder, foldersFirst]);

  const handleNavigate = (folderName: string) => {
    // Navigate into user-created folders
    const isUserFolder = files.some(f => f.type === "folder" && f.name === folderName);

    if (isUserFolder) {
      setCurrentPath([...currentPath, folderName]);
      setSelectedFilter("all"); // Reset filter when navigating
    }
  };

  const handleBreadcrumbClick = (index: number) => {
    if (index === 0) {
      // If clicking on Home, explicitly set to Home
      setCurrentPath(["Home"]);
    } else {
      setCurrentPath(currentPath.slice(0, index + 1));
    }
  };

  const handleCopy = (itemsToCopy: FileItem | FileItem[]) => {
    const itemsList = Array.isArray(itemsToCopy) ? itemsToCopy : [itemsToCopy];
    if (itemsList.length === 0) return;
    const firstItem = itemsList[0];
    const sourcePath = isInboxMode 
      ? "/Telegram Inbox" 
      : (firstItem.file_path || currentApiPath || (currentPath.length > 1 ? `/${currentPath.join('/')}` : "/Home"));
    copyItem(itemsList, sourcePath);
    if (itemsList.length === 1) {
      toast.success(`Copied "${itemsList[0].name}"`);
    } else {
      toast.success(`Copied ${itemsList.length} items`);
    }
  };

  const handleCut = (itemsToCut: FileItem | FileItem[]) => {
    const itemsList = Array.isArray(itemsToCut) ? itemsToCut : [itemsToCut];
    if (itemsList.length === 0) return;
    const firstItem = itemsList[0];
    const sourcePath = isInboxMode 
      ? "/Telegram Inbox" 
      : (firstItem.file_path || currentApiPath || (currentPath.length > 1 ? `/${currentPath.join('/')}` : "/Home"));
    cutItem(itemsList, sourcePath);
    if (itemsList.length === 1) {
      toast.success(`Cut "${itemsList[0].name}"`);
    } else {
      toast.success(`Cut ${itemsList.length} items`);
    }
  };

  const handlePaste = async () => {
    try {
      // Construct the target path using current location
      const targetPath = currentApiPath || (currentPath.length > 1 ? `/${currentPath.join('/')}` : "/Home");
      
      await pasteItem(targetPath);
      toast.success("Operation completed successfully");
      // Refresh current location after paste
      refetch();
    } catch (error: any) {
      toast.error(error.message || "Failed to complete operation");
    }
  };

  const handleFilterChange = (filter: string) => {
    // Map filter to folder name
    const folderMap: Record<string, string> = {
      all: "Home",
      inbox: "Telegram Inbox",
      starred: "Starred",
      trash: "Trash",
    };
    
    const folderName = folderMap[filter] || "Home";
    // For virtual folders, we need to include the full path
    if (folderName !== "Home") {
      setCurrentPath(["Home", folderName]);
    } else {
      setCurrentPath([folderName]);
    }
    setSelectedFilter(filter);

    // Reset filters on section change
    setTypeFilter("all");
    setSizeFilter("all");
    setDateFilter("all");

    // Set intelligent default sort for each section
    if (filter === "inbox") {
      setSortField("date");
      setSortOrder("desc"); // Newest forwarded files first
      setFoldersFirst(false);
    } else if (filter === "trash") {
      setSortField("date");
      setSortOrder("desc"); // Recently trashed files first
      setFoldersFirst(true);
    } else if (filter === "starred") {
      setSortField("date");
      setSortOrder("desc");
      setFoldersFirst(true);
    } else {
      setSortField("name");
      setSortOrder("asc");
      setFoldersFirst(true);
    }
  };

  const handleSidebarDrop = async (item: FileItem, targetFolderName: string) => {
    try {
      // Construct the source path correctly
      let sourcePath = "/";
      if (isInboxMode) {
        sourcePath = "/Telegram Inbox";
      } else if (currentPath.length > 1) {
        // For all folder types, we construct the path consistently
        sourcePath = `/${currentPath.join('/')}`;
      }
      
      // Construct the target path
      let targetPath = "/Home";
      if (targetFolderName === "Telegram Inbox") {
        targetPath = "/Telegram Inbox";
      } else if (targetFolderName !== "Home") {
        // Since folders are now in the database, we can construct the path directly
        targetPath = `/Home/${targetFolderName}`;
      }
      
      const baseUrl = getApiBaseUrl();
      // For the default case, we need to append /api to the base URL
      const apiUrl = baseUrl ? `${baseUrl}` : '';
      
      const response = await fetchWithTimeout(`${apiUrl}/files/move`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include", // Add this to include cookies for authentication
        body: JSON.stringify({
          file_id: item.id,  // Use file_id instead of file_path
          target_path: targetPath,
        }),
      }, 3000); // 3 second timeout

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to move file");
      }

      toast.success(`Moved "${item.name}" to ${targetFolderName}`);
      // Refresh current location after drag and drop
      refetch();
    } catch (error: any) {
      toast.error(error.message || "Failed to move file");
    }
  };

  const handleNewFolder = async (folderName: string) => {
    try {
      // Use currentApiPath which correctly handles /Home and subfolders
      const backendPath = currentApiPath;
      
      const baseUrl = getApiBaseUrl();
      // For the default case, we need to append /api to the base URL
      const apiUrl = baseUrl ? `${baseUrl}` : '';
      
      const response = await fetchWithTimeout(`${apiUrl}/folders/create`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include", // Add this to include cookies for authentication
        body: JSON.stringify({
          folderName,
          currentPath: backendPath,
        }),
      }, 3000); // 3 second timeout

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to create folder");
      }

      toast.success(`Folder "${folderName}" created successfully`);
      setNewFolderDialogOpen(false);
      // Refresh current location after creating folder
      refetch();
    } catch (error: any) {
      toast.error(error.message || "Failed to create folder");
    }
  };

  // Add the missing functions
  const handleDelete = (item: FileItem, index: number) => {
    setDeleteDialog({ item, index });
  };

  const handleRename = (item: FileItem, index: number) => {
    setRenamingItem({ item, index });
  };

  const handleMove = async (item: FileItem, targetFolder: FileItem) => {
    try {
      // Determine source path from item or current path
      let sourcePath = item.file_path || (currentPath.length > 1 ? `/${currentPath.join('/')}` : "/Home");
      
      // Construct the target path dynamically based on targetFolder's actual location
      let targetPath = "/Home";
      
      if (targetFolder.name === "Home") {
        targetPath = "/Home";
      } else if (targetFolder.file_path) {
        // Use the folder's actual parent path in the file tree
        const parent = targetFolder.file_path.replace(/\/+$/, '');
        targetPath = parent && parent !== "/" ? `${parent}/${targetFolder.name}` : `/${targetFolder.name}`;
      } else {
        // Fallback using currentApiPath
        const current = currentApiPath || (currentPath.length > 1 ? `/${currentPath.join('/')}` : "/Home");
        targetPath = `${current.replace(/\/+$/, '')}/${targetFolder.name}`;
      }
      
      // Ensure paths are properly formatted
      sourcePath = sourcePath.replace(/\/+/g, '/'); // Remove duplicate slashes
      targetPath = targetPath.replace(/\/+/g, '/'); // Remove duplicate slashes
      
      // Ensure targetPath doesn't end with a slash unless it's root
      if (targetPath !== "/" && targetPath.endsWith("/")) {
        targetPath = targetPath.slice(0, -1);
      }
      
      await moveItem(item, targetPath, sourcePath);
      toast.success(`Moved "${item.name}" to ${targetFolder.name}`);
      // Refresh current location after move
      refetch();
    } catch (error: any) {
      logger.error("Error moving file", { error, item, targetFolder });
      toast.error(error.message || "Failed to move file");
    }
  };

  const handleDownloadFolderPart = (part: FolderPartInfo) => {
    const baseUrl = getApiBaseUrl();
    const downloadUrl = part.download_url.startsWith('http')
      ? part.download_url
      : `${baseUrl || ''}${part.download_url}`;
    downloadManager.addDownload(downloadUrl, part.name);
    toast.success(`Started download for ${part.name}`);
  };

  const handleDownloadAllFolderParts = (parts: FolderPartInfo[]) => {
    const baseUrl = getApiBaseUrl();
    parts.forEach((part, index) => {
      setTimeout(() => {
        const downloadUrl = part.download_url.startsWith('http')
          ? part.download_url
          : `${baseUrl || ''}${part.download_url}`;
        downloadManager.addDownload(downloadUrl, part.name);
      }, index * 400);
    });
    toast.success(`Queued ${parts.length} parts for download`);
  };

  const handleDownload = async (item: FileItem) => {
    try {
      const baseUrl = getApiBaseUrl();

      if (item.type === "folder") {
        toast.info(`Preparing zip for "${item.name}"...`);
        const token = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
        const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
        const param = item.id
          ? `id=${encodeURIComponent(item.id)}`
          : `path=${encodeURIComponent(item.file_path ? `${item.file_path}/${item.name}` : (currentApiPath ? `${currentApiPath}/${item.name}` : `/Home/${item.name}`))}`;

        const response = await fetchWithTimeout(
          `${baseUrl || ""}/folders/download-info?${param}${tokenParam}`,
          { credentials: "include" }
        );

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.detail || `Failed to prepare folder download: ${response.status}`);
        }

        const info: FolderDownloadInfo = await response.json();
        if (!info.parts || info.parts.length === 0) {
          toast.warning("Folder is empty or has no files to download.");
          return;
        }

        if (info.parts.length === 1) {
          // Single part (<= 2GB), start download directly
          const part = info.parts[0];
          handleDownloadFolderPart(part);
        } else {
          // Multiple parts (> 2GB), show part selection dialog
          setFolderDownloadInfo(info);
        }
        return;
      }

      console.log('[FileExplorer] handleDownload - baseUrl:', baseUrl);
      
      // Construct the download URL - for the new path structure, we just need the file name
      // The backend will handle extracting the file name from paths like /Home/Images/filename.jpg
      const fileName = item.name;
      let downloadUrl = baseUrl 
        ? `${baseUrl}/dl/${fileName}` 
        : `/dl/${fileName}`;
      
      console.log('[FileExplorer] handleDownload - constructed URL:', downloadUrl);
      
      // Add to download manager for tracking - this will automatically start the download
      // The download manager will handle adding auth tokens as needed
      const downloadId = downloadManager.addDownload(downloadUrl, item.name);
      
      // The download is now handled by the download manager's queue system
      // We don't need to call downloadFile directly
    } catch (error: any) {
      logger.error("Failed to download file:", error);
      toast.error(error.message || "Failed to download file");
    }
  };


  const confirmRename = async (newName: string) => {
    if (!renamingItem) return;

    try {
      const item = renamingItem.item;
      const backendPath = currentApiPath;
      
      const baseUrl = getApiBaseUrl();
      // For the default case, we need to append /api to the base URL
      const apiUrl = baseUrl ? `${baseUrl}` : '';
      
      const response = await fetchWithTimeout(`${apiUrl}/files/rename`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include", // Add this to include cookies for authentication
        body: JSON.stringify({
          file_id: item.id,  // Use file_id instead of file_path
          new_name: newName,
        }),
      }, 3000); // 3 second timeout

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to rename file");
      }

      toast.success(`Renamed "${item.name}" to "${newName}"`);
      setRenamingItem(null);
      // Refresh current location after renaming file
      refetch();
    } catch (error: any) {
      toast.error(error.message || "Failed to rename file");
    }
  };

  const confirmDelete = async () => {
    if (!deleteDialog) return;

    try {
      const item = deleteDialog.item;
      if (!item.id) return;

      if (isTrashMode) {
        await api.deleteForever(item.id);
        toast.success(`Permanently deleted "${item.name}"`);
      } else {
        await api.trashFile(item.id);
        toast.success(`Moved "${item.name}" to Trash`);
      }
      setDeleteDialog(null);
      // Refresh current location after deleting file
      refetch();
    } catch (error: any) {
      toast.error(error.message || "Failed to delete item");
    }
  };

  const handleToggleStar = async (item: FileItem) => {
    if (!item.id) return;
    try {
      const newStarred = !item.starred;
      await api.toggleStar(item.id, newStarred);
      toast.success(newStarred ? `Added "${item.name}" to Starred` : `Removed "${item.name}" from Starred`);
      refetch();
    } catch (error: any) {
      toast.error(error.message || "Failed to update star status");
    }
  };

  const handleRestoreItem = async (item: FileItem) => {
    if (!item.id) return;
    try {
      await api.restoreFile(item.id);
      toast.success(`Restored "${item.name}"`);
      refetch();
    } catch (error: any) {
      toast.error(error.message || "Failed to restore item");
    }
  };

  const handleEmptyTrash = async () => {
    try {
      setIsEmptyingTrash(true);
      const res = await api.emptyTrash();
      toast.success(res.message || "Trash emptied successfully");
      setEmptyTrashDialogOpen(false);
      refetch();
    } catch (error: any) {
      toast.error(error.message || "Failed to empty trash");
    } finally {
      setIsEmptyingTrash(false);
    }
  };

  const cancelDelete = () => {
    setDeleteDialog(null);
  };

  // Determine the selected filter based on the current path
  useEffect(() => {
    // Map folder name to filter
    const folderMap: Record<string, string> = {
      "Home": "all",
      "Telegram Inbox": "inbox",
      "Starred": "starred",
      "Trash": "trash",
    };
    
    // If we're in a default folder, select the corresponding filter
    const currentFolderName = currentPath[currentPath.length - 1];
    const filter = folderMap[currentFolderName] || "all";
    
    // Only update if it's different to prevent infinite loops
    if (selectedFilter !== filter) {
      setSelectedFilter(filter);
    }
  }, [currentPath, selectedFilter]);

  // Sync category changes with NavigationSidebar for mobile
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('currentCategoryChanged', { detail: { filter: selectedFilter } }));
  }, [selectedFilter]);

  useEffect(() => {
    const handleCategoryChange = (e: CustomEvent) => {
      if (e.detail?.filter) {
        setShowProfile(false);
        setShowSettings(false);
        setShowUserManagement(false);
        setShowStorageAnalytics(false);
        handleFilterChange(e.detail.filter);
      }
    };
    window.addEventListener('changeCategory', handleCategoryChange as EventListener);
    return () => window.removeEventListener('changeCategory', handleCategoryChange as EventListener);
  }, []);

  const activeView: 'files' | 'profile' | 'settings' | 'users' | 'storage' | 'transfers' | 'downloads' = 
    showProfile ? 'profile' :
    showSettings ? 'settings' :
    showUserManagement ? 'users' :
    showStorageAnalytics ? 'storage' :
    showTransfers ? 'transfers' : 'files';

  const handleNavigateView = (view: 'files' | 'profile' | 'settings' | 'users' | 'storage' | 'transfers' | 'downloads', filter?: string) => {
    if (view === 'profile') {
      setShowProfile(true);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
      setShowTransfers(false);
      navigate('/profile');
    } else if (view === 'settings') {
      setShowSettings(true);
      setShowProfile(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
      setShowTransfers(false);
      navigate('/settings');
    } else if (view === 'users') {
      setShowUserManagement(true);
      setShowProfile(false);
      setShowSettings(false);
      setShowStorageAnalytics(false);
      setShowTransfers(false);
      navigate('/users');
    } else if (view === 'storage') {
      setShowStorageAnalytics(true);
      setShowProfile(false);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowTransfers(false);
      navigate('/storage');
    } else if (view === 'transfers' || view === 'downloads') {
      setShowTransfers(true);
      setShowProfile(false);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
      navigate('/transfers');
    } else {
      setShowProfile(false);
      setShowSettings(false);
      setShowUserManagement(false);
      setShowStorageAnalytics(false);
      setShowTransfers(false);
      navigate('/');
      if (filter) {
        handleFilterChange(filter);
      }
    }
  };

  return (
    <div className="flex h-full w-full bg-background text-foreground select-none min-h-0 overflow-hidden">
      <Sidebar
        currentPath={currentPath}
        onNavigate={handleFilterChange}
        onDrop={handleSidebarDrop}
        files={files}
        selectedFilter={selectedFilter}
        activeView={activeView}
        onNavigateView={handleNavigateView}
        onOpenWebDAV={() => setShowWebDAVDialog(true)}
        isCollapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(prev => !prev)}
        onNewFolder={() => setNewFolderDialogOpen(true)}
        mobileOpen={mobileDrawerOpen}
        onCloseMobile={() => setMobileDrawerOpen(false)}
      />

      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {showProfile ? (
          <motion.div
            key="profile"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="flex-1 flex flex-col h-full min-h-0 overflow-hidden"
          >
            <ProfileContent onBack={() => {
              setShowProfile(false);
              navigate('/');
            }} />
          </motion.div>
        ) : showSettings ? (
          <motion.div
            key="settings"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="flex-1 flex flex-col h-full min-h-0 overflow-hidden"
          >
            <SettingsContent onBack={() => {
              setShowSettings(false);
              navigate('/');
            }} />
          </motion.div>
        ) : showUserManagement ? (
          <motion.div
            key="user-management"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="flex-1 flex flex-col h-full min-h-0 overflow-hidden"
          >
            <UserManagementContent onBack={() => {
              setShowUserManagement(false);
              navigate('/');
            }} />
          </motion.div>
        ) : showStorageAnalytics ? (
          <motion.div
            key="storage-analytics"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="flex-1 flex flex-col h-full min-h-0 overflow-hidden"
          >
            <StorageAnalyticsContent
              onBack={() => {
                setShowStorageAnalytics(false);
                navigate('/');
              }}
              onOpenTrash={() => {
                setShowStorageAnalytics(false);
                navigate('/');
                handleFilterChange("trash");
              }}
            />
          </motion.div>
        ) : showTransfers ? (
          <motion.div
            key="transfers"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="flex-1 flex flex-col h-full min-h-0 overflow-hidden"
          >
            <Transfers />
          </motion.div>
        ) : (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            <TopBar
              currentPath={currentPath}
              searchQuery={searchQuery}
              viewMode={viewMode}
              onSearchChange={setSearchQuery}
              onViewModeChange={setViewMode}
              onBack={() => window.history.back()}
              onRefresh={refetch}
              onBreadcrumbClick={handleBreadcrumbClick}
              onToggleSidebar={() => {
                if (window.innerWidth < 768) {
                  setMobileDrawerOpen(prev => !prev);
                } else {
                  setSidebarCollapsed(prev => !prev);
                }
              }}
              sortField={sortField}
              sortOrder={sortOrder}
              foldersFirst={foldersFirst}
              onSortChange={(field, order) => {
                setSortField(field);
                setSortOrder(order);
              }}
              onFoldersFirstChange={setFoldersFirst}
              typeFilter={typeFilter}
              onTypeFilterChange={setTypeFilter}
              sizeFilter={sizeFilter}
              onSizeFilterChange={setSizeFilter}
              dateFilter={dateFilter}
              onDateFilterChange={setDateFilter}
              onResetFilters={() => {
                setTypeFilter("all");
                setSizeFilter("all");
                setDateFilter("all");
                setSearchQuery("");
              }}
              typeCounts={typeCounts}
              totalCount={baseItems.length}
              filteredCount={filteredItems.length}
              isInboxMode={isInboxMode}
            />

            {/* Trash Banner */}
            {isTrashMode && (
              <div className="flex items-center justify-between px-4 py-2.5 bg-amber-500/10 border-b border-amber-500/20 text-sm">
                <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300">
                  <AlertCircle className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" />
                  <span>Items in Trash are kept until emptied or permanently deleted.</span>
                </div>
                {filteredItems.length > 0 && (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setEmptyTrashDialogOpen(true)}
                    className="h-7 text-xs font-medium px-3 gap-1.5 shrink-0"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    Empty Trash
                  </Button>
                )}
              </div>
            )}

            <FileGrid
              items={filteredItems}
              viewMode={viewMode}
              onNavigate={handleNavigate}
              itemCount={filteredItems.length}
              onCopy={handleCopy}
              onCut={handleCut}
              onPaste={hasClipboard && !isClipboardPasted() ? handlePaste : undefined}
              onDelete={handleDelete}
              onRename={handleRename}
              onMove={handleMove}
              onDownload={handleDownload}
              renamingItem={renamingItem}
              onRenameConfirm={confirmRename}
              onRenameCancel={() => setRenamingItem(null)}
              currentFolder={currentFolder}
              currentPath={currentPath}
              currentApiPath={currentApiPath}
              onNewFolder={() => setNewFolderDialogOpen(true)}
              isLoading={isLoading}
              cutItem={clipboard?.operation === "cut" && !isClipboardPasted() ? clipboard.item : null}
              cutItems={clipboard?.operation === "cut" && !isClipboardPasted() ? cutItems : []}
              hasClipboard={hasClipboard}
              isClipboardPasted={isClipboardPasted()}
              onRefresh={refetch}
              isTrashMode={isTrashMode}
              onRestoreItem={handleRestoreItem}
              onToggleStar={handleToggleStar}
            />

          </div>
        )}
      </div>


      <DeleteDialog
        open={!!deleteDialog}
        itemName={deleteDialog?.item.name || ""}
        itemType={deleteDialog?.item.type || "file"}
        onConfirm={confirmDelete}
        onCancel={cancelDelete}
        isTrashMode={isTrashMode}
      />

      {/* Empty Trash Confirmation Dialog */}
      <AlertDialog open={emptyTrashDialogOpen} onOpenChange={setEmptyTrashDialogOpen}>
        <AlertDialogContent className="bg-background/95 backdrop-blur-md border border-border rounded-xl shadow-2xl max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Empty Trash?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to permanently delete all items in the Trash? This will delete all files and messages from Telegram channels permanently. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isEmptyingTrash} onClick={() => setEmptyTrashDialogOpen(false)}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={isEmptyingTrash}
              onClick={(e) => {
                e.preventDefault();
                handleEmptyTrash();
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isEmptyingTrash ? "Emptying..." : "Empty Trash"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <NewFolderDialog
        open={newFolderDialogOpen}
        currentPath={currentApiPath}  // Pass the full path, not just the folder name
        onClose={() => setNewFolderDialogOpen(false)}
        onConfirm={handleNewFolder}
      />

      <FolderDownloadDialog
        open={!!folderDownloadInfo}
        info={folderDownloadInfo}
        onClose={() => setFolderDownloadInfo(null)}
        onDownloadPart={handleDownloadFolderPart}
        onDownloadAll={handleDownloadAllFolderParts}
      />

      <WebDAVMountDialog
        open={showWebDAVDialog}
        onOpenChange={setShowWebDAVDialog}
      />

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          itemType={contextMenu.itemType}
          itemName={contextMenu.itemName}
          isVideo={contextMenu.item ? isVideoItem(contextMenu.item) : false}
          onCopyStreamUrl={() => {
            if (contextMenu.item) {
              copyStreamUrl(contextMenu.item.name);
            }
          }}
          onOpen={() => {
            if (contextMenu.item && contextMenu.item.type === "folder") {
              handleNavigate(contextMenu.item.name);
            }
          }}
          onCopy={() => contextMenu.item && handleCopy(contextMenu.item)}
          onCut={() => contextMenu.item && handleCut(contextMenu.item)}
          onPaste={hasClipboard && !isClipboardPasted() ? handlePaste : undefined}
          onDelete={() => contextMenu.item && handleDelete(contextMenu.item, contextMenu.index || 0)}
          onRename={() => contextMenu.item && handleRename(contextMenu.item, contextMenu.index || 0)}
          onNewFolder={() => setNewFolderDialogOpen(true)}
          onClose={() => setContextMenu(null)}
          isClipboardPasted={isClipboardPasted()} // Pass the clipboard pasted status
          hasClipboard={hasClipboard} // Pass the clipboard status function
          isStarred={contextMenu.item?.starred}
          onToggleStar={() => contextMenu.item && handleToggleStar(contextMenu.item)}
          isTrashMode={isTrashMode}
          onRestore={() => contextMenu.item && handleRestoreItem(contextMenu.item)}
          disableDelete={
            // Disable delete for specific default folders in Home
            currentPath.length === 1 && 
            currentPath[0] === "Home" && 
            contextMenu.item && 
            ["Images", "Documents", "Audio", "Voice Messages", "Videos"].includes(contextMenu.item.name)
          }
        />
      )}
    </div>
  );
};