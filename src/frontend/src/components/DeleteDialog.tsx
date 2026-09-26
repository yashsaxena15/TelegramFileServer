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

interface DeleteDialogProps {
  open: boolean;
  itemName: string;
  itemType: "file" | "folder";
  onConfirm: () => void;
  onCancel: () => void;
  isTrashMode?: boolean;
  isCloudMode?: boolean;
}

export const DeleteDialog = ({
  open,
  itemName,
  itemType,
  onConfirm,
  onCancel,
  isTrashMode = false,
  isCloudMode = false,
}: DeleteDialogProps) => {
  const getTitle = () => {
    if (isCloudMode) {
      return isTrashMode
        ? `Permanently delete ${itemType} from Google Drive?`
        : `Move ${itemType} to Google Drive Trash?`;
    }
    return isTrashMode ? `Permanently delete ${itemType}?` : `Move ${itemType} to Trash?`;
  };

  const getButtonText = () => {
    if (isCloudMode) {
      return isTrashMode ? "Delete Forever from Drive" : "Move to Drive Trash";
    }
    return isTrashMode ? "Delete Forever" : "Move to Trash";
  };

  return (
    <AlertDialog open={open} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent className="bg-background/95 backdrop-blur-md border border-border rounded-xl shadow-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle>
            {getTitle()}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {isTrashMode ? (
              <>
                Are you sure you want to permanently delete &quot;{itemName}&quot;{isCloudMode ? " from your Google Drive" : ""}?
                {itemType === "folder" && " This will remove all files and subfolders permanently."}
                {" This action cannot be undone."}
              </>
            ) : (
              <>
                Are you sure you want to move &quot;{itemName}&quot; to {isCloudMode ? "Google Drive's Trash (Bin)" : "Trash"}?
                {itemType === "folder" && " All items inside this folder will also be moved to Trash."}
                {" You can restore it later from the Trash folder."}
              </>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {getButtonText()}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};