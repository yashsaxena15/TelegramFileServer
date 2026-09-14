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
}

export const DeleteDialog = ({
  open,
  itemName,
  itemType,
  onConfirm,
  onCancel,
  isTrashMode = false,
}: DeleteDialogProps) => {
  return (
    <AlertDialog open={open} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent className="bg-background/95 backdrop-blur-md border border-border rounded-xl shadow-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle>
            {isTrashMode ? `Permanently delete ${itemType}?` : `Move ${itemType} to Trash?`}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {isTrashMode ? (
              <>
                Are you sure you want to permanently delete &quot;{itemName}&quot;?
                {itemType === "folder" && " This will remove all files and subfolders permanently."}
                {" This action cannot be undone."}
              </>
            ) : (
              <>
                Are you sure you want to move &quot;{itemName}&quot; to Trash?
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
            {isTrashMode ? "Delete Forever" : "Move to Trash"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};