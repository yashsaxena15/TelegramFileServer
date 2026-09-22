import { toast } from "sonner";
import { getApiBaseUrl, fetchWithTimeout } from "@/lib/api";

/**
 * Tracks an asynchronous background archive task (extraction or compression),
 * updating a Sonner toast with real-time stage, progress percentage, and file names.
 */
export function trackArchiveTask(
  taskId: string,
  taskType: "extract" | "compress",
  targetName: string,
  onComplete?: () => void
) {
  const baseUrl = getApiBaseUrl();
  const label = taskType === "extract" ? "Extraction" : "Compression";
  const toastId = toast.loading(`[${label}] ${targetName}: Starting...`);

  const pollInterval = setInterval(async () => {
    try {
      const res = await fetchWithTimeout(`${baseUrl ? baseUrl : ""}/api/archive/tasks/${taskId}`, {}, 10000);
      if (!res.ok) return;
      const data = await res.json();

      if (data.status === "completed") {
        clearInterval(pollInterval);
        toast.success(`[${label} Completed] ${targetName} processed successfully!`, { id: toastId });
        if (onComplete) onComplete();
      } else if (data.status === "failed") {
        clearInterval(pollInterval);
        toast.error(`[${label} Failed] ${data.error || "Operation failed"}`, { id: toastId });
      } else if (data.status === "cancelled") {
        clearInterval(pollInterval);
        toast.info(`[${label} Cancelled] ${targetName}`, { id: toastId });
      } else {
        const pct = Math.round(data.progress_percent || 0);
        let msg = `${targetName}: ${pct}%`;
        if (data.stage === "downloading") {
          msg = `Downloading archive: ${pct}%`;
        } else if (data.stage === "extracting") {
          msg = `Extracting ${targetName} (${pct}%)...`;
        } else if (data.stage === "uploading") {
          if (data.total_files > 0) {
            msg = `Uploading (${data.processed_files || 0}/${data.total_files}) ${data.current_file ? '- ' + data.current_file : ''}`;
          } else {
            msg = `Uploading to Telegram: ${pct}%`;
          }
        } else if (data.stage === "compressing") {
          if (data.total_files > 0) {
            msg = `Compressing (${data.processed_files || 0}/${data.total_files}) ${data.current_file ? '- ' + data.current_file : ''}`;
          } else {
            msg = `Compressing ${targetName}: ${pct}%`;
          }
        }
        toast.loading(`[${label}] ${msg}`, { id: toastId });
      }
    } catch {
      // Ignore transient polling network drops
    }
  }, 2500);
}
