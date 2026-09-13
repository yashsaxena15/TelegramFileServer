export interface FileItem {
  id?: string;
  file_unique_id?: string;
  name: string;
  type: "file" | "folder";
  icon: string;
  extension?: string;
  size?: number;
  fileType?: 'document' | 'video' | 'photo' | 'voice' | 'audio' | 'folder';
  thumbnail?: string | null;
  file_path?: string;  // Path where file is located (folder name)
  modified?: string;  // ISO format date string for when file was last modified
  chat_id?: number;
  message_id?: number;
  caption?: string;
}

export interface ApiFile {
  id: string;
  chat_id: number;
  message_id: number;
  file_type: 'document' | 'video' | 'photo' | 'voice' | 'audio' | 'folder';
  thumbnail: string | null;
  file_unique_id: string;
  file_size: number;
  file_name: string | null;
  file_caption: string | null;
  file_path: string;  // Path where file is located
}

const VIDEO_EXTS = ['mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'wmv', 'm4v', '3gp', 'ts'];
const PHOTO_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'heic'];
const AUDIO_EXTS = ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac', 'opus', 'wma'];

// Utility function to get icon based on file type
export const getFileIcon = (fileType: string, fileName?: string): string => {
  const extension = fileName?.split('.').pop()?.toLowerCase() || '';

  if (fileType === 'folder') return '📁';
  if (fileType === 'photo' || PHOTO_EXTS.includes(extension)) return '🖼️';
  if (fileType === 'video' || VIDEO_EXTS.includes(extension)) return '🎬';
  if (fileType === 'audio' || fileType === 'voice' || AUDIO_EXTS.includes(extension)) return '🎵';
  if (extension === 'pdf') return '📄';
  if (['doc', 'docx'].includes(extension)) return '📝';
  if (['xls', 'xlsx'].includes(extension)) return '📊';
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(extension)) return '📦';
  return '📄';
};

// Convert API file to FileItem
export const apiFileToFileItem = (apiFile: any): FileItem => {
  const fileName = apiFile.file_name || `${apiFile.file_type}_${apiFile.message_id}`;
  const extension = fileName.split('.').pop()?.toLowerCase();

  let resolvedFileType = apiFile.file_type;
  if (resolvedFileType === 'document' || !resolvedFileType) {
    if (VIDEO_EXTS.includes(extension || '')) resolvedFileType = 'video';
    else if (PHOTO_EXTS.includes(extension || '')) resolvedFileType = 'photo';
    else if (AUDIO_EXTS.includes(extension || '')) resolvedFileType = 'audio';
  }

  return {
    id: apiFile.id,
    file_unique_id: apiFile.file_unique_id,
    name: fileName,
    type: apiFile.file_type === 'folder' ? 'folder' : 'file',
    icon: getFileIcon(resolvedFileType, fileName),
    extension: extension !== fileName ? extension : undefined,
    size: apiFile.file_size,
    fileType: resolvedFileType,
    thumbnail: apiFile.thumbnail,
    file_path: apiFile.file_path,
    modified: apiFile.modified_date,
    chat_id: apiFile.chat_id,
    message_id: apiFile.message_id,
    caption: apiFile.file_caption,
  };
};