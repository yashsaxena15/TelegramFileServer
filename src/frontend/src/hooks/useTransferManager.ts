import { useState, useEffect, useMemo, useCallback } from 'react';
import { uploadManager, UploadItem } from '@/lib/uploadManager';
import { downloadManager, DownloadItem } from '@/lib/downloadManager';
import { transferManager } from '@/lib/transferManager';

export const useTransferManager = () => {
  const [uploads, setUploads] = useState<UploadItem[]>(() => uploadManager.getUploads());
  const [downloads, setDownloads] = useState<DownloadItem[]>(() => downloadManager.getDownloads());

  useEffect(() => {
    const unsubUpload = uploadManager.subscribe(setUploads);
    const unsubDownload = downloadManager.subscribe(setDownloads);
    return () => {
      unsubUpload();
      unsubDownload();
    };
  }, []);

  const activeUploads = useMemo(
    () => uploads.filter(u => u.status === 'uploading' || u.status === 'queued'),
    [uploads]
  );

  const activeDownloads = useMemo(
    () => downloads.filter(d => d.status === 'downloading' || d.status === 'queued'),
    [downloads]
  );

  const totalActiveCount = activeUploads.length + activeDownloads.length;

  const stats = useMemo(() => {
    return {
      activeUploads: activeUploads.length,
      activeDownloads: activeDownloads.length,
      totalActive: totalActiveCount,
      completedUploads: uploads.filter(u => u.status === 'completed').length,
      completedDownloads: downloads.filter(d => d.status === 'completed').length,
      failedUploads: uploads.filter(u => u.status === 'failed').length,
      failedDownloads: downloads.filter(d => d.status === 'failed').length,
      pausedCount: uploads.filter(u => u.status === 'paused').length + downloads.filter(d => d.status === 'paused').length
    };
  }, [uploads, downloads, activeUploads, activeDownloads, totalActiveCount]);

  // Upload Actions
  const pauseUpload = useCallback((id: string) => uploadManager.pauseUpload(id), []);
  const resumeUpload = useCallback((id: string) => uploadManager.resumeUpload(id), []);
  const cancelUpload = useCallback((id: string) => uploadManager.cancelUpload(id), []);
  const retryUpload = useCallback((id: string) => uploadManager.retryUpload(id), []);

  // Download Actions
  const pauseDownload = useCallback((id: string) => downloadManager.pauseDownload(id), []);
  const resumeDownload = useCallback((id: string) => downloadManager.resumeDownload(id), []);
  const cancelDownload = useCallback((id: string) => downloadManager.cancelDownload(id), []);
  const retryDownload = useCallback((download: DownloadItem) => {
    downloadManager.cancelDownload(download.id);
    downloadManager.addDownload(download.url, download.filename);
  }, []);

  // Bulk Actions
  const pauseAll = useCallback(() => transferManager.pauseAll(), []);
  const resumeAll = useCallback(() => transferManager.resumeAll(), []);
  const cancelAll = useCallback(() => transferManager.cancelAll(), []);
  const clearCompleted = useCallback(() => transferManager.clearCompleted(), []);

  return {
    uploads,
    downloads,
    activeUploads,
    activeDownloads,
    totalActiveCount,
    stats,
    pauseUpload,
    resumeUpload,
    cancelUpload,
    retryUpload,
    pauseDownload,
    resumeDownload,
    cancelDownload,
    retryDownload,
    pauseAll,
    resumeAll,
    cancelAll,
    clearCompleted
  };
};
