import { useState } from "react";
import { Plus, FolderPlus, FileUp, FolderUp } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FloatingUploadButtonProps {
  onUploadFiles?: () => void;
  onUploadFolder?: () => void;
  onCreateFolder?: () => void;
}

export const FloatingUploadButton = ({
  onUploadFiles,
  onUploadFolder,
  onCreateFolder,
}: FloatingUploadButtonProps) => {
  const [isOpen, setIsOpen] = useState(false);

  const handleFileUpload = () => {
    if (onUploadFiles) {
      onUploadFiles();
    } else {
      const fileGridElement = document.querySelector('[data-drag-container]');
      if (fileGridElement) {
        const fileInput = fileGridElement.querySelector('input[type="file"]:not([webkitdirectory])') as HTMLInputElement;
        fileInput?.click();
      }
    }
    setIsOpen(false);
  };

  const handleFolderUpload = () => {
    if (onUploadFolder) {
      onUploadFolder();
    } else {
      const fileGridElement = document.querySelector('[data-drag-container]');
      if (fileGridElement) {
        const directoryInput = fileGridElement.querySelector('input[type="file"][webkitdirectory]') as HTMLInputElement;
        directoryInput?.click();
      }
    }
    setIsOpen(false);
  };

  const handleNewFolder = () => {
    if (onCreateFolder) {
      onCreateFolder();
    }
    setIsOpen(false);
  };

  return (
    <>
      {isOpen && (
        <div 
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-xs animate-in fade-in duration-200" 
          onClick={() => setIsOpen(false)} 
        />
      )}
      <div className="fixed bottom-5 right-5 sm:bottom-6 sm:right-6 z-40">
        {/* Google Drive style options when open */}
        {isOpen && (
          <div className="absolute bottom-16 right-0 flex flex-col gap-2 mb-2 min-w-44 animate-in slide-in-from-bottom-3 duration-200">
            {onCreateFolder && (
              <Button
                onClick={handleNewFolder}
                className="flex items-center justify-start gap-2.5 bg-background/95 backdrop-blur-md border border-border hover:bg-accent shadow-xl min-h-[44px] px-4 text-sm rounded-xl"
                variant="outline"
              >
                <FolderPlus className="w-4 h-4 text-blue-500" />
                <span className="font-medium">New folder</span>
              </Button>
            )}
            <Button
              onClick={handleFileUpload}
              className="flex items-center justify-start gap-2.5 bg-background/95 backdrop-blur-md border border-border hover:bg-accent shadow-xl min-h-[44px] px-4 text-sm rounded-xl"
              variant="outline"
            >
              <FileUp className="w-4 h-4 text-emerald-500" />
              <span className="font-medium">Upload file</span>
            </Button>
            <Button
              onClick={handleFolderUpload}
              className="flex items-center justify-start gap-2.5 bg-background/95 backdrop-blur-md border border-border hover:bg-accent shadow-xl min-h-[44px] px-4 text-sm rounded-xl"
              variant="outline"
            >
              <FolderUp className="w-4 h-4 text-amber-500" />
              <span className="font-medium">Upload folder</span>
            </Button>
          </div>
        )}

        {/* Main Google Drive style '+' floating button */}
        <Button
          onClick={() => setIsOpen(!isOpen)}
          className={`rounded-2xl w-14 h-14 shadow-2xl transition-all duration-300 ${
            isOpen
              ? "bg-muted-foreground hover:bg-muted-foreground/90 rotate-45 text-white"
              : "bg-primary hover:bg-primary/90 text-primary-foreground hover:scale-105"
          }`}
          size="icon"
          title="New (Google Drive style)"
        >
          <Plus className="w-7 h-7 stroke-[2.5]" />
        </Button>
      </div>
    </>
  );
};