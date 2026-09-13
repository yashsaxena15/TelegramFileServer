import { useState } from "react";
import { Upload, File, Folder } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FloatingUploadButtonProps {
  onUploadFiles?: () => void;
  onUploadFolder?: () => void;
}

export const FloatingUploadButton = ({
  onUploadFiles,
  onUploadFolder,
}: FloatingUploadButtonProps) => {
  const [isOpen, setIsOpen] = useState(false);

  const handleFileUpload = () => {
    // Trigger file upload through FileGrid's ref or by exposing the function
    const fileGridElement = document.querySelector('[data-drag-container]');
    if (fileGridElement) {
      const fileInput = fileGridElement.querySelector('input[type="file"]:not([webkitdirectory])') as HTMLInputElement;
      fileInput?.click();
    }
    setIsOpen(false);
  };

  const handleFolderUpload = () => {
    // Trigger folder upload through FileGrid's ref or by exposing the function
    const fileGridElement = document.querySelector('[data-drag-container]');
    if (fileGridElement) {
      const directoryInput = fileGridElement.querySelector('input[type="file"][webkitdirectory]') as HTMLInputElement;
      directoryInput?.click();
    }
    setIsOpen(false);
  };

  return (
    <>
      {isOpen && (
        <div 
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-xs" 
          onClick={() => setIsOpen(false)} 
        />
      )}
      <div className="fixed bottom-5 right-5 sm:bottom-6 sm:right-6 z-40">
        {/* Upload options when open */}
        {isOpen && (
          <div className="absolute bottom-16 right-0 flex flex-col gap-2 mb-2">
            <Button
              onClick={handleFileUpload}
              className="flex items-center gap-2 bg-background border border-border hover:bg-accent shadow-lg min-h-[44px] px-4 text-sm"
              variant="outline"
            >
              <File className="w-4 h-4" />
              Upload Files
            </Button>
            <Button
              onClick={handleFolderUpload}
              className="flex items-center gap-2 bg-background border border-border hover:bg-accent shadow-lg min-h-[44px] px-4 text-sm"
              variant="outline"
            >
              <Folder className="w-4 h-4" />
              Upload Folder
            </Button>
          </div>
        )}

        {/* Main floating button */}
        <Button
          onClick={() => setIsOpen(!isOpen)}
          className="rounded-full w-12 h-12 sm:w-14 sm:h-14 shadow-lg hover:shadow-xl transition-shadow"
          size="icon"
        >
          <Upload className="w-5 h-5 sm:w-6 sm:h-6" />
        </Button>
      </div>
    </>
  );
};