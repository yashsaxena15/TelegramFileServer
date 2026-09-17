import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileItem } from "@/components/types";
import { getApiBaseUrl, fetchWithTimeout } from "@/lib/api";
import logger from "@/lib/logger";

// Define the request interface
interface CopyMoveRequest {
  file_id: string;
  target_path: string;
}

interface MoveRequest {
  file_id: string;
  target_path: string;
}

interface ClipboardItem {
  items: FileItem[];
  item?: FileItem; // For backward compatibility
  operation: "copy" | "cut";
  sourcePath: string;
  pasted?: boolean; // Track if the item has been pasted
}

export const useFileOperations = () => {
  const [clipboard, setClipboard] = useState<ClipboardItem | null>(null);
  const queryClient = useQueryClient();

  const copyItem = (items: FileItem | FileItem[], sourcePath: string) => {
    const itemList = Array.isArray(items) ? items : [items];
    logger.info("Copying items", { count: itemList.length, sourcePath });
    setClipboard({ items: itemList, item: itemList[0], operation: "copy", sourcePath, pasted: false });
  };

  const cutItem = (items: FileItem | FileItem[], sourcePath: string) => {
    const itemList = Array.isArray(items) ? items : [items];
    logger.info("Cutting items", { count: itemList.length, sourcePath });
    setClipboard({ items: itemList, item: itemList[0], operation: "cut", sourcePath, pasted: false });
  };

  const clearClipboard = () => {
    logger.info("Clearing clipboard");
    setClipboard(null);
  };

  const markAsPasted = () => {
    if (clipboard) {
      setClipboard({ ...clipboard, pasted: true });
    }
  };

  const hasClipboard = () => clipboard !== null && clipboard.items && clipboard.items.length > 0;
  
  const isClipboardPasted = () => clipboard?.pasted === true;

  const pasteItem = async (targetPath: string) => {
    if (!clipboard || !clipboard.items || clipboard.items.length === 0) {
      logger.warn("No item in clipboard to paste");
      return;
    }

    const { items, operation, sourcePath } = clipboard;
    logger.info(`Pasting ${items.length} item(s)`, { 
      operation, 
      count: items.length, 
      sourcePath, 
      targetPath 
    });

    try {
      // Ensure paths are properly formatted
      const cleanSourcePath = sourcePath.replace(/\/+/g, '/');
      let cleanTargetPath = targetPath.replace(/\/+/g, '/');
      
      // Ensure targetPath doesn't end with a slash unless it's the root
      if (cleanTargetPath !== "/" && cleanTargetPath.endsWith("/")) {
        cleanTargetPath = cleanTargetPath.slice(0, -1);
      }

      const baseUrl = getApiBaseUrl();
      const apiUrl = baseUrl ? `${baseUrl}` : '';
      const endpoint = operation === "copy" ? `${apiUrl}/files/copy` : `${apiUrl}/files/move`;

      const results = await Promise.allSettled(
        items.map(async (item) => {
          const fileId = item.id || (item as any)._id;
          if (!fileId) throw new Error(`Missing ID for ${item.name}`);

          const request: CopyMoveRequest = {
            file_id: String(fileId),
            target_path: cleanTargetPath
          };

          const response = await fetchWithTimeout(endpoint, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            credentials: "include",
            body: JSON.stringify(request),
          }, 15000);

          if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Failed to ${operation} "${item.name}": ${errorText}`);
          }
        })
      );

      const rejected = results.filter((r): r is PromiseRejectedResult => r.status === "rejected");
      if (rejected.length > 0) {
        const errorMsg = rejected.map(r => r.reason?.message || "Operation failed").join(", ");
        logger.error("Some paste operations failed", { errorMsg });
        if (rejected.length === items.length) {
          throw new Error(errorMsg);
        }
      }

      // Refresh all file queries
      queryClient.invalidateQueries({ queryKey: ['files'] });

      // If this was a cut operation, clear the clipboard so files are not moved again
      if (operation === "cut") {
        clearClipboard();
      } else {
        markAsPasted();
      }

      return true;
    } catch (error) {
      logger.error("Error during paste operation", error);
      throw error;
    }
  };

  const moveItem = async (item: FileItem, targetPath: string, sourcePath: string) => {
    logger.info("Moving item", { 
      item: item.name, 
      sourcePath, 
      targetPath 
    });

    try {
      // Ensure paths are properly formatted
      sourcePath = sourcePath.replace(/\/+/g, '/'); // Remove duplicate slashes
      targetPath = targetPath.replace(/\/+/g, '/'); // Remove duplicate slashes
      
      // Ensure targetPath doesn't end with a slash unless it's the root
      if (targetPath !== "/" && targetPath.endsWith("/")) {
        targetPath = targetPath.slice(0, -1);
      }

      const baseUrl = getApiBaseUrl();
      const apiUrl = baseUrl ? `${baseUrl}` : '';
      const request: MoveRequest = {
        file_id: item.id || "",
        target_path: targetPath
      };

      logger.info("Performing move operation", { request });
      const response = await fetchWithTimeout(`${apiUrl}/files/move`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify(request),
      }, 10000);

      if (!response.ok) {
        const errorText = await response.text();
        logger.error("Failed to move file", { status: response.status, error: errorText });
        
        if (response.status === 404) {
          throw new Error(`File not found: ${item.name}`);
        } else if (response.status === 500) {
          throw new Error(`Server error while moving file: ${errorText}`);
        } else {
          throw new Error(`Failed to move file: ${errorText}`);
        }
      }
      
      logger.info("File moved successfully");
      queryClient.invalidateQueries({ queryKey: ['files'] });
      
      return true;
    } catch (error) {
      logger.error("Error during move operation", error);
      throw error;
    }
  };

  return {
    clipboard,
    clipboardItems: clipboard?.items || [],
    cutItems: clipboard?.operation === 'cut' ? clipboard.items : [],
    copyItem,
    cutItem,
    clearClipboard,
    hasClipboard,
    isClipboardPasted,
    pasteItem,
    moveItem,
  };
};