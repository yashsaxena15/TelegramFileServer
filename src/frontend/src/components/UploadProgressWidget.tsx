import { useState, useEffect, useRef } from "react";

export interface FileUploadStatus {
  fileName: string;
  filePath: string;
  progress: number;
  status: 'uploading' | 'completed' | 'failed';
  error?: string;
  loaded?: number;
  total?: number;
  speed?: string;
  eta?: string;
}

interface UploadProgressWidgetProps {
  files: File[];
  currentPath: string;
  isDirectoryUpload?: boolean;
  uploadProgress?: Record<string, FileUploadStatus>;
  onComplete: () => void;
  onCancel: () => void;
}

const formatBytes = (bytes?: number): string => {
  if (!bytes || bytes <= 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

export const UploadProgressWidget = ({ 
  files, 
  currentPath, 
  isDirectoryUpload = false,
  uploadProgress,
  onComplete, 
  onCancel 
}: UploadProgressWidgetProps) => {
  const [isVisible, setIsVisible] = useState(false);
  const completionTimer = useRef<NodeJS.Timeout | null>(null);
  const closeTimer = useRef<NodeJS.Timeout | null>(null);
  const [hasCompleted, setHasCompleted] = useState(false);

  useEffect(() => {
    const entranceTimer = setTimeout(() => {
      setIsVisible(true);
    }, 10);
    return () => clearTimeout(entranceTimer);
  }, []);

  // Derive items from uploadProgress prop if available, otherwise map from files
  const items: FileUploadStatus[] = uploadProgress 
    ? Object.values(uploadProgress)
    : files.map(file => {
        let filePath = file.name;
        if (isDirectoryUpload && 'webkitRelativePath' in file) {
          filePath = (file as any).webkitRelativePath || file.name;
        }
        return {
          fileName: file.name,
          filePath,
          progress: 0,
          status: 'uploading',
          loaded: 0,
          total: file.size
        };
      });

  // Calculate overall progress based on loaded bytes if available
  const totalLoaded = items.reduce((sum, item) => sum + (item.loaded || 0), 0);
  const totalBytes = items.reduce((sum, item) => sum + (item.total || 0), 0);

  const overallProgress = totalBytes > 0 
    ? Math.min(100, Math.round((totalLoaded / totalBytes) * 100))
    : (items.length > 0 ? items.reduce((sum, i) => sum + i.progress, 0) / items.length : 0);

  // Find active speed and eta among uploading items
  const activeUploadingItem = items.find(i => i.status === 'uploading' && i.speed);
  const activeSpeed = activeUploadingItem?.speed;
  const activeEta = activeUploadingItem?.eta;

  // Monitor completion
  useEffect(() => {
    if (items.length === 0 || hasCompleted) return;

    const allFinished = items.every(i => i.status === 'completed' || i.status === 'failed');
    const allSuccessful = items.every(i => i.status === 'completed');

    if (allFinished && allSuccessful) {
      setHasCompleted(true);
      // Wait 1.5 seconds for visual confirmation of completion before fading out
      completionTimer.current = setTimeout(() => {
        setIsVisible(false);
        closeTimer.current = setTimeout(() => {
          onComplete();
        }, 300);
      }, 1500);
    }

    return () => {
      if (completionTimer.current) clearTimeout(completionTimer.current);
      if (closeTimer.current) clearTimeout(closeTimer.current);
    };
  }, [items, hasCompleted, onComplete]);

  return (
    <div className={`fixed bottom-4 right-4 z-50 w-96 max-w-[92vw] bg-background border border-border rounded-lg shadow-xl transition-all duration-300 ease-in-out ${
      isVisible ? 'transform translate-y-0 opacity-100' : 'transform translate-y-full opacity-0'
    }`}>
      <div className="p-4">
        <div className="flex justify-between items-center mb-2">
          <h3 className="font-semibold text-sm truncate">
            {isDirectoryUpload ? 'Uploading folder to' : 'Uploading to'} {currentPath}
          </h3>
          <button 
            onClick={onCancel}
            className="text-muted-foreground hover:text-foreground text-sm px-1.5 py-0.5 rounded hover:bg-muted"
            title="Close"
          >
            ✕
          </button>
        </div>
        
        {/* Progress bar */}
        <div className="w-full bg-secondary rounded-full h-2 mb-2">
          <div 
            className="bg-primary h-2 rounded-full transition-all duration-300" 
            style={{ width: `${overallProgress}%` }}
          ></div>
        </div>

        {/* Progress stats and real-time speed */}
        <div className="flex flex-col gap-1 text-xs text-muted-foreground mb-3">
          <div className="flex justify-between font-medium">
            <span>{Math.round(overallProgress)}%</span>
            {totalBytes > 0 && (
              <span>{formatBytes(totalLoaded)} of {formatBytes(totalBytes)}</span>
            )}
          </div>
          {(activeSpeed || activeEta) && (
            <div className="flex justify-between text-[11px] text-primary font-mono">
              {activeSpeed && <span>⚡ {activeSpeed}</span>}
              {activeEta && <span>⏱️ ETA: {activeEta}</span>}
            </div>
          )}
        </div>
        
        {/* File items list */}
        <div className="space-y-2 max-h-60 overflow-y-auto custom-scrollbar">
          {items.map((item, index) => (
            <div key={index} className="flex flex-col gap-1 text-sm p-1.5 rounded hover:bg-muted/50">
              <div className="flex items-center gap-2">
                <div className="flex-shrink-0 w-4">
                  {item.status === 'uploading' && (
                    <div className="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
                  )}
                  {item.status === 'completed' && (
                    <span className="text-green-500 font-bold">✓</span>
                  )}
                  {item.status === 'failed' && (
                    <span className="text-red-500 font-bold">✗</span>
                  )}
                </div>
                <div className="flex-1 truncate font-medium text-xs" title={item.filePath}>
                  {item.filePath}
                </div>
                <div className="text-xs text-muted-foreground flex-shrink-0">
                  {item.status === 'uploading' && (
                    item.progress >= 99 
                      ? <span className="text-blue-500 animate-pulse">Forwarding to Telegram...</span> 
                      : `${Math.round(item.progress)}%`
                  )}
                  {item.status === 'completed' && <span className="text-green-600 dark:text-green-400 font-medium">Done</span>}
                  {item.status === 'failed' && <span className="text-destructive font-medium">Failed</span>}
                </div>
              </div>

              {item.status === 'uploading' && item.total && item.total > 0 && (
                <div className="flex justify-between text-[11px] text-muted-foreground pl-6 font-mono">
                  <span>{formatBytes(item.loaded)} / {formatBytes(item.total)}</span>
                  {item.speed && <span>{item.speed}</span>}
                </div>
              )}

              {item.status === 'failed' && item.error && (
                <div className="text-[11px] text-destructive pl-6 truncate" title={item.error}>
                  {item.error}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};