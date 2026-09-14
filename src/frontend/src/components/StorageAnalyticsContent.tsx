import { useState, useEffect } from "react";
import { 
  ArrowLeft, 
  HardDrive, 
  Video, 
  Music, 
  Image as ImageIcon, 
  FileText, 
  Archive, 
  File, 
  Trash2, 
  Star, 
  RefreshCw,
  Folder,
  Files
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "./ui/card";
import { Button } from "./ui/button";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/utils";

interface StorageAnalyticsContentProps {
  onBack: () => void;
  onOpenTrash?: () => void;
}

interface AnalyticsData {
  total_bytes: number;
  total_files: number;
  total_folders: number;
  trash_bytes: number;
  trash_count: number;
  starred_count: number;
  by_category: {
    video: { count: number; bytes: number };
    audio: { count: number; bytes: number };
    photo: { count: number; bytes: number };
    document: { count: number; bytes: number };
    archive: { count: number; bytes: number };
    other: { count: number; bytes: number };
  };
  largest_files: Array<{
    id: string;
    file_unique_id?: string;
    file_name: string;
    file_size: number;
    file_type: string;
    file_path: string;
    thumbnail?: string | null;
    modified_date?: string;
  }>;
}

export const StorageAnalyticsContent = ({ onBack, onOpenTrash }: StorageAnalyticsContentProps) => {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchAnalytics = async () => {
    try {
      setLoading(true);
      const res = await api.getStorageAnalytics();
      setData(res);
    } catch (error: any) {
      toast.error("Failed to load storage analytics", {
        description: error.message || String(error),
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics();
  }, []);

  const totalBytes = data?.total_bytes || 0;

  const categories = [
    { key: "video", label: "Videos", icon: Video, color: "bg-blue-500", textColor: "text-blue-500", rawColor: "#3b82f6" },
    { key: "audio", label: "Audio & Voice", icon: Music, color: "bg-purple-500", textColor: "text-purple-500", rawColor: "#a855f7" },
    { key: "photo", label: "Images", icon: ImageIcon, color: "bg-emerald-500", textColor: "text-emerald-500", rawColor: "#10b981" },
    { key: "document", label: "Documents", icon: FileText, color: "bg-amber-500", textColor: "text-amber-500", rawColor: "#f59e0b" },
    { key: "archive", label: "Archives", icon: Archive, color: "bg-rose-500", textColor: "text-rose-500", rawColor: "#f43f5e" },
    { key: "other", label: "Other", icon: File, color: "bg-slate-400", textColor: "text-slate-400", rawColor: "#94a3b8" },
  ];

  return (
    <div className="flex-1 overflow-y-auto bg-gradient-to-br from-slate-50 to-blue-50/30 dark:from-gray-950 dark:to-gray-900 p-4 sm:p-6 select-none">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Top Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              onClick={onBack}
              className="rounded-full hover:bg-muted"
            >
              <ArrowLeft className="w-5 h-5" />
            </Button>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2.5">
                <HardDrive className="w-6 h-6 text-blue-600 dark:text-blue-400" />
                Storage & Analytics
              </h1>
              <p className="text-xs text-muted-foreground">
                Overview of your cloud storage footprint, files, and category distribution
              </p>
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={fetchAnalytics}
            disabled={loading}
            className="gap-2 text-xs h-8"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {/* Main Total Storage Card */}
        <Card className="border-border shadow-sm bg-card/80 backdrop-blur-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold flex items-center justify-between">
              <span>Total Cloud Storage Used</span>
              <span className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                {formatBytes(totalBytes)}
              </span>
            </CardTitle>
            <CardDescription className="text-xs">
              Storage utilized across all folders in your Telegram storage
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-1">
            {/* Multi-segment Progress Bar */}
            <div className="w-full h-3.5 bg-muted rounded-full overflow-hidden flex shadow-inner">
              {totalBytes > 0 ? (
                categories.map((cat) => {
                  const catBytes = data?.by_category?.[cat.key as keyof typeof data.by_category]?.bytes || 0;
                  const pct = totalBytes > 0 ? (catBytes / totalBytes) * 100 : 0;
                  if (pct <= 0) return null;
                  return (
                    <div
                      key={cat.key}
                      style={{ width: `${pct}%`, backgroundColor: cat.rawColor }}
                      className="h-full transition-all duration-300"
                      title={`${cat.label}: ${formatBytes(catBytes)} (${pct.toFixed(1)}%)`}
                    />
                  );
                })
              ) : (
                <div className="w-full h-full bg-muted" />
              )}
            </div>

            {/* Legend */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3 pt-2">
              {categories.map((cat) => {
                const catData = data?.by_category?.[cat.key as keyof typeof data.by_category];
                const catBytes = catData?.bytes || 0;
                const catCount = catData?.count || 0;
                const pct = totalBytes > 0 ? (catBytes / totalBytes) * 100 : 0;

                return (
                  <div key={cat.key} className="flex items-start gap-2 text-xs">
                    <span
                      style={{ backgroundColor: cat.rawColor }}
                      className="w-2.5 h-2.5 rounded-full shrink-0 mt-0.5"
                    />
                    <div className="min-w-0">
                      <div className="font-medium text-foreground truncate">{cat.label}</div>
                      <div className="text-[11px] text-muted-foreground">{formatBytes(catBytes)}</div>
                      <div className="text-[10px] text-muted-foreground/80">{catCount} files ({pct.toFixed(0)}%)</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {/* Quick Stats Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Card className="bg-card/70 border-border">
            <CardContent className="p-4 flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 flex items-center justify-center shrink-0">
                <Files className="w-5 h-5" />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Total Files</div>
                <div className="text-lg font-bold text-foreground">{data?.total_files ?? 0}</div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card/70 border-border">
            <CardContent className="p-4 flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 flex items-center justify-center shrink-0">
                <Folder className="w-5 h-5" />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Folders</div>
                <div className="text-lg font-bold text-foreground">{data?.total_folders ?? 0}</div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card/70 border-border">
            <CardContent className="p-4 flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 flex items-center justify-center shrink-0">
                <Star className="w-5 h-5" />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Starred Items</div>
                <div className="text-lg font-bold text-foreground">{data?.starred_count ?? 0}</div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card/70 border-border">
            <CardContent className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-rose-500/10 text-rose-600 dark:text-rose-400 flex items-center justify-center shrink-0">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Recycle Bin</div>
                  <div className="text-sm font-bold text-foreground">
                    {data?.trash_count ?? 0} items ({formatBytes(data?.trash_bytes || 0)})
                  </div>
                </div>
              </div>
              {onOpenTrash && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onOpenTrash}
                  className="text-xs h-7 px-2 text-muted-foreground hover:text-foreground"
                >
                  View
                </Button>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Top 10 Largest Files */}
        <Card className="border-border bg-card/80 backdrop-blur-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">Top Largest Files</CardTitle>
            <CardDescription className="text-xs">
              Files consuming the most storage space in your account
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {data?.largest_files && data.largest_files.length > 0 ? (
              <div className="divide-y divide-border">
                {data.largest_files.map((file, idx) => (
                  <div
                    key={file.id || idx}
                    className="flex items-center justify-between px-4 py-2.5 hover:bg-muted/40 transition-colors text-xs"
                  >
                    <div className="flex items-center gap-3 min-w-0 pr-4">
                      <span className="font-mono text-muted-foreground/70 w-5 text-center shrink-0">
                        #{idx + 1}
                      </span>
                      <div className="min-w-0">
                        <div className="font-medium text-foreground truncate max-w-sm sm:max-w-md">
                          {file.file_name}
                        </div>
                        <div className="text-[11px] text-muted-foreground truncate">
                          {file.file_path || "/Home"}
                        </div>
                      </div>
                    </div>

                    <div className="shrink-0 font-semibold font-mono text-foreground text-right">
                      {formatBytes(file.file_size)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-6 text-center text-xs text-muted-foreground">
                No files found in storage yet.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
