// src/frontend/src/lib/transferGrouping.ts

import { RemoteTransferItem } from '@/hooks/useTransferManager';

export interface GroupedRemoteTransfer {
  isGroup: true;
  type: 'remote';
  id: string;
  task_id: string;
  group_id: string;
  group_name: string;
  group_type?: 'folder' | 'torrent';
  filename: string;
  destination_path: string;
  status: 'queued' | 'downloading' | 'uploading_tg' | 'completed' | 'failed' | 'cancelled';
  phase?: string;
  filesize: number;
  transferred_bytes: number;
  bytesUploaded: number;
  downloaded: number;
  speed_bps: number;
  speed: number;
  progress: number;
  eta_seconds: number;
  eta: number;
  peer_count: number;
  items: (RemoteTransferItem & {
    type: 'remote';
    filesize: number;
    bytesUploaded: number;
    downloaded: number;
    file: null;
    startTime: string;
  })[];
  completedCount: number;
  totalCount: number;
  startTime: string;
}

export function groupRemoteTransfers(remoteTransfers: RemoteTransferItem[]) {
  const groupMap = new Map<string, any[]>();
  const singleRemoteItems: any[] = [];

  remoteTransfers.forEach(r => {
    const item = {
      ...r,
      type: 'remote' as const,
      filesize: r.filesize || 0,
      bytesUploaded: r.transferred_bytes || 0,
      downloaded: r.transferred_bytes || 0,
      file: null,
      startTime: r.created_at
    };
    if (r.group_id) {
      if (!groupMap.has(r.group_id)) {
        groupMap.set(r.group_id, []);
      }
      groupMap.get(r.group_id)!.push(item);
    } else {
      singleRemoteItems.push(item);
    }
  });

  const groupedRemoteItems: GroupedRemoteTransfer[] = [];
  groupMap.forEach((subItems, groupId) => {
    const completedCount = subItems.filter(i => i.status === 'completed').length;
    const failedCount = subItems.filter(i => i.status === 'failed').length;
    const cancelledCount = subItems.filter(i => i.status === 'cancelled').length;
    const isDownloading = subItems.some(i => i.status === 'downloading');
    const isUploading = subItems.some(i => i.status === 'uploading_tg');
    const isQueued = subItems.some(i => i.status === 'queued');

    let status: 'queued' | 'downloading' | 'uploading_tg' | 'completed' | 'failed' | 'cancelled' = 'queued';
    if (isDownloading) status = 'downloading';
    else if (isUploading) status = 'uploading_tg';
    else if (completedCount === subItems.length && subItems.length > 0) status = 'completed';
    else if (cancelledCount === subItems.length && subItems.length > 0) status = 'cancelled';
    else if (failedCount === subItems.length && subItems.length > 0) status = 'failed';
    else if (isQueued) status = 'queued';

    const totalBytes = subItems.reduce((acc, i) => acc + (i.filesize || 0), 0);
    const transferredBytes = subItems.reduce((acc, i) => acc + (i.transferred_bytes || 0), 0);
    const totalSpeed = subItems.reduce((acc, i) => acc + (i.speed_bps || 0), 0);
    const totalPeers = subItems.reduce((acc, i) => acc + (i.peer_count || 0), 0);

    let progress = 0;
    if (totalBytes > 0) {
      progress = Math.min(100, Math.round((transferredBytes / totalBytes) * 1000) / 10);
    } else if (subItems.length > 0) {
      progress = Math.min(100, Math.round((completedCount / subItems.length) * 1000) / 10);
    }

    const groupName = subItems[0].group_name || 'Folder Download';
    const groupType = subItems[0].group_type || 'folder';
    const destPath = subItems[0].destination_path || '/Home';

    let phase = '';
    if (status === 'completed') {
      phase = `Completed all ${subItems.length} file(s) 🎉`;
    } else if (status === 'downloading' || status === 'uploading_tg') {
      const activeSub = subItems.find(i => i.status === 'downloading' || i.status === 'uploading_tg');
      phase = `Leeching [${completedCount + 1}/${subItems.length}]: ${activeSub?.filename || ''}`;
    } else if (status === 'cancelled') {
      phase = 'Folder transfer cancelled';
    } else {
      phase = `Queued (${subItems.length} files)`;
    }

    groupedRemoteItems.push({
      isGroup: true,
      type: 'remote' as const,
      id: groupId,
      task_id: groupId,
      group_id: groupId,
      group_name: groupName,
      group_type: groupType,
      filename: groupName,
      destination_path: destPath,
      status,
      phase,
      filesize: totalBytes,
      transferred_bytes: transferredBytes,
      bytesUploaded: transferredBytes,
      downloaded: transferredBytes,
      speed_bps: totalSpeed,
      speed: totalSpeed,
      progress,
      eta_seconds: 0,
      eta: 0,
      peer_count: totalPeers,
      items: subItems,
      completedCount,
      totalCount: subItems.length,
      startTime: subItems[0].startTime
    });
  });

  return { groupedRemoteItems, singleRemoteItems };
}
