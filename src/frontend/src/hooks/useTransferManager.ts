import { useState, useEffect, useMemo, useCallback } from 'react';
import { uploadManager, UploadItem } from '@/lib/uploadManager';
import { downloadManager, DownloadItem } from '@/lib/downloadManager';
import { transferManager } from '@/lib/transferManager';
import { api } from '@/lib/api';

export interface RemoteTransferItem {
  id: string;
  task_id: string;
  source_url: string;
  source_type: string;
  destination_path: string;
  filename: string;
  name: string;
  filesize: number;
  size: number;
  transferred_bytes: number;
  bytesUploaded: number;
  progress: number;
  speed_bps: number;
  speed: number;
  eta_seconds: number;
  eta: number;
  status: 'queued' | 'downloading' | 'uploading_tg' | 'completed' | 'failed' | 'cancelled';
  phase?: string;
  error_message?: string;
  is_vault?: boolean;
  type: 'remote';
  created_at: string;
}

export const useTransferManager = () => {
  const [uploads, setUploads] = useState<UploadItem[]>(() => uploadManager.getUploads());
  const [downloads, setDownloads] = useState<DownloadItem[]>(() => downloadManager.getDownloads());
  const [remoteTransfers, setRemoteTransfers] = useState<RemoteTransferItem[]>([]);

  useEffect(() => {
    const unsubUpload = uploadManager.subscribe(setUploads);
    const unsubDownload = downloadManager.subscribe(setDownloads);
    return () => {
      unsubUpload();
      unsubDownload();
    };
  }, []);

  const fetchRemoteTransfers = useCallback(async () => {
    try {
      const res = await api.getRemoteTasks();
      if (res && Array.isArray(res.tasks)) {
        const mapped: RemoteTransferItem[] = res.tasks.map(t => ({
          ...t,
          id: t.task_id,
          name: t.filename || 'Remote Transfer',
          size: t.filesize || 0,
          bytesUploaded: t.transferred_bytes || 0,
          speed: t.speed_bps || 0,
          eta: t.eta_seconds || 0,
          type: 'remote' as const
        }));
        setRemoteTransfers(mapped);
      }
    } catch {
      // Ignore background poll errors
    }
  }, []);

  const hasActiveRemote = useMemo(
    () => remoteTransfers.some(r => r.status === 'downloading' || r.status === 'uploading_tg' || r.status === 'queued'),
    [remoteTransfers]
  );

  useEffect(() => {
    fetchRemoteTransfers();
    const intervalTime = hasActiveRemote ? 1500 : 8000;
    const interval = setInterval(fetchRemoteTransfers, intervalTime);
    return () => clearInterval(interval);
  }, [fetchRemoteTransfers, hasActiveRemote]);

  // Listen to remoteTransferAdded custom event
  useEffect(() => {
    const handleRemoteAdded = () => fetchRemoteTransfers();
    window.addEventListener('remoteTransferAdded', handleRemoteAdded);
    return () => window.removeEventListener('remoteTransferAdded', handleRemoteAdded);
  }, [fetchRemoteTransfers]);

  const activeUploads = useMemo(
    () => uploads.filter(u => u.status === 'uploading' || u.status === 'queued'),
    [uploads]
  );

  const activeDownloads = useMemo(
    () => downloads.filter(d => d.status === 'downloading' || d.status === 'queued'),
    [downloads]
  );

  const activeRemote = useMemo(
    () => remoteTransfers.filter(r => r.status === 'downloading' || r.status === 'uploading_tg' || r.status === 'queued'),
    [remoteTransfers]
  );

  const totalActiveCount = activeUploads.length + activeDownloads.length + activeRemote.length;

  const stats = useMemo(() => {
    return {
      activeUploads: activeUploads.length,
      activeDownloads: activeDownloads.length,
      activeRemote: activeRemote.length,
      totalActive: totalActiveCount,
      completedUploads: uploads.filter(u => u.status === 'completed').length,
      completedDownloads: downloads.filter(d => d.status === 'completed').length,
      completedRemote: remoteTransfers.filter(r => r.status === 'completed').length,
      failedUploads: uploads.filter(u => u.status === 'failed').length,
      failedDownloads: downloads.filter(d => d.status === 'failed').length,
      failedRemote: remoteTransfers.filter(r => r.status === 'failed').length,
      pausedCount: uploads.filter(u => u.status === 'paused').length + downloads.filter(d => d.status === 'paused').length
    };
  }, [uploads, downloads, remoteTransfers, activeUploads, activeDownloads, activeRemote, totalActiveCount]);

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

  // Remote Transfer Actions
  const cancelRemoteTransfer = useCallback(async (taskId: string) => {
    try {
      await api.cancelRemoteTask(taskId);
      setRemoteTransfers(prev => prev.map(t => t.task_id === taskId ? { ...t, status: 'cancelled', phase: 'Cancelled by user' } : t));
    } catch (e) {
      console.error(e);
    }
  }, []);

  const clearCompletedRemote = useCallback(async () => {
    try {
      await api.clearCompletedRemoteTasks();
      setRemoteTransfers(prev => prev.filter(t => t.status !== 'completed' && t.status !== 'cancelled' && t.status !== 'failed'));
    } catch (e) {
      console.error(e);
    }
  }, []);

  // Bulk Actions
  const pauseAll = useCallback(() => transferManager.pauseAll(), []);
  const resumeAll = useCallback(() => transferManager.resumeAll(), []);
  const cancelAll = useCallback(() => {
    transferManager.cancelAll();
    // Cancel all active remote tasks as well
    remoteTransfers
      .filter(r => r.status === 'downloading' || r.status === 'uploading_tg' || r.status === 'queued')
      .forEach(r => cancelRemoteTransfer(r.task_id));
  }, [remoteTransfers, cancelRemoteTransfer]);

  const clearCompleted = useCallback(() => {
    transferManager.clearCompleted();
    clearCompletedRemote();
  }, [clearCompletedRemote]);

  return {
    uploads,
    downloads,
    remoteTransfers,
    activeUploads,
    activeDownloads,
    activeRemote,
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
    cancelRemoteTransfer,
    clearCompletedRemote,
    refreshRemoteTransfers: fetchRemoteTransfers,
    pauseAll,
    resumeAll,
    cancelAll,
    clearCompleted
  };
};
