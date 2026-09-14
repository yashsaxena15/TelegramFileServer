import React, { createContext, useContext, useState, ReactNode } from "react";
import { MediaPlayer } from "@/components/MediaPlayer";
import { FileItem } from "@/components/types";
import { downloadManager } from "@/lib/downloadManager";

export interface ActiveMedia {
  url: string;
  fileName: string;
  fileType: "video" | "audio" | "voice";
  fileItem?: FileItem;
}

interface MediaPlayerContextType {
  currentMedia: ActiveMedia | null;
  playMedia: (media: ActiveMedia) => void;
  closeMedia: () => void;
}

const MediaPlayerContext = createContext<MediaPlayerContextType | undefined>(undefined);

export const MediaPlayerProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [currentMedia, setCurrentMedia] = useState<ActiveMedia | null>(null);

  const playMedia = (media: ActiveMedia) => {
    // If the previous media was a blob URL, revoke it
    if (currentMedia?.url && currentMedia.url !== media.url && currentMedia.url.startsWith("blob:")) {
      try {
        URL.revokeObjectURL(currentMedia.url);
      } catch (e) {}
    }
    setCurrentMedia(media);
  };

  const closeMedia = () => {
    if (currentMedia?.url.startsWith("blob:")) {
      try {
        URL.revokeObjectURL(currentMedia.url);
      } catch (e) {}
    }
    setCurrentMedia(null);
  };

  return (
    <MediaPlayerContext.Provider value={{ currentMedia, playMedia, closeMedia }}>
      {children}
      {currentMedia && (
        <MediaPlayer
          key={currentMedia.url}
          mediaUrl={currentMedia.url}
          fileName={currentMedia.fileName}
          fileType={currentMedia.fileType}
          onDownload={() => {
            downloadManager.addDownload(currentMedia.url, currentMedia.fileName);
          }}
          onClose={closeMedia}
        />
      )}
    </MediaPlayerContext.Provider>
  );
};

export const useMediaPlayer = () => {
  const context = useContext(MediaPlayerContext);
  if (!context) {
    throw new Error("useMediaPlayer must be used within a MediaPlayerProvider");
  }
  return context;
};
