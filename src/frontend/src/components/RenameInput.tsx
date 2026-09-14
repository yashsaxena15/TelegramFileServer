import { useState, useEffect, useRef } from "react";
import { Input } from "./ui/input";
import { toast } from "sonner";

interface RenameInputProps {
  initialName: string;
  onSave: (newName: string) => void;
  onCancel: () => void;
}

const FORBIDDEN_CHARS_REGEX = /[/\\:*?"<>|\x00-\x1f]/;

export const RenameInput = ({ initialName, onSave, onCancel }: RenameInputProps) => {
  const [value, setValue] = useState(initialName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
      // Select filename without extension
      const lastDotIndex = initialName.lastIndexOf(".");
      if (lastDotIndex > 0) {
        inputRef.current.setSelectionRange(0, lastDotIndex);
      } else {
        inputRef.current.select();
      }
    }
  }, [initialName]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || trimmed === initialName) {
      onCancel();
      return;
    }
    if (trimmed.length > 60) {
      toast.error("Name cannot exceed 60 characters");
      onCancel();
      return;
    }
    if (FORBIDDEN_CHARS_REGEX.test(trimmed)) {
      toast.error('Name cannot contain: / \\ : * ? " < > |');
      onCancel();
      return;
    }
    if (trimmed === "." || trimmed === "..") {
      toast.error("Name cannot be '.' or '..'");
      onCancel();
      return;
    }
    onSave(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSubmit();
    } else if (e.key === "Escape") {
      onCancel();
    }
  };

  return (
    <Input
      ref={inputRef}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={handleSubmit}
      onKeyDown={handleKeyDown}
      className="h-7 text-xs bg-background"
      onClick={(e) => e.stopPropagation()}
    />
  );
};
