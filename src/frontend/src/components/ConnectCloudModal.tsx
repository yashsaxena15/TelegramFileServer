import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ChevronDown, ChevronUp, Cloud, ExternalLink, ShieldCheck, CheckCircle2 } from "lucide-react";

interface ConnectCloudModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

export const ConnectCloudModal: React.FC<ConnectCloudModalProps> = ({
  open,
  onOpenChange,
  onSuccess,
}) => {
  const [selectedProvider, setSelectedProvider] = useState<string>("google_drive");
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [customClientId, setCustomClientId] = useState<string>("");
  const [customClientSecret, setCustomClientSecret] = useState<string>("");
  const [isConnecting, setIsConnecting] = useState<boolean>(false);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === "GDRIVE_AUTH_SUCCESS") {
        toast.success(`Google Drive successfully connected: ${event.data.email}`);
        setIsConnecting(false);
        onSuccess();
        onOpenChange(false);
      } else if (event.data?.type === "GDRIVE_AUTH_ERROR") {
        toast.error(`Authorization failed: ${event.data.error}`);
        setIsConnecting(false);
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [onSuccess, onOpenChange]);

  const handleConnectGoogle = async () => {
    setIsConnecting(true);
    try {
      const res = await api.getGoogleAuthUrl(
        customClientId.trim() || undefined,
        customClientSecret.trim() || undefined
      );

      // Open Google OAuth consent in a popup window
      const width = 560;
      const height = 680;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;
      
      const popup = window.open(
        res.auth_url,
        "gdrive_oauth_popup",
        `width=${width},height=${height},left=${left},top=${top},toolbar=0,scrollbars=1,status=1,resizable=1`
      );

      if (!popup || popup.closed || typeof popup.closed === "undefined") {
        // If popup was blocked by browser, redirect current tab
        window.location.href = res.auth_url;
        return;
      }

      // Check for popup close
      const timer = setInterval(() => {
        if (popup.closed) {
          clearInterval(timer);
          setIsConnecting(false);
        }
      }, 1000);
    } catch (err: any) {
      toast.error(err.message || "Failed to start Google Drive connection.");
      setIsConnecting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md bg-background border border-border/80 rounded-xl shadow-2xl p-6">
        <DialogHeader>
          <div className="flex items-center gap-2.5 text-primary mb-1">
            <div className="p-2 rounded-lg bg-primary/10">
              <Cloud className="w-5 h-5 text-primary" />
            </div>
            <DialogTitle className="text-lg font-bold">Connect Cloud Storage</DialogTitle>
          </div>
          <DialogDescription className="text-sm text-muted-foreground">
            Link your cloud storage to browse files and stream them directly into your Telegram storage without downloading.
          </DialogDescription>
        </DialogHeader>

        {/* Provider List */}
        <div className="space-y-3 py-3">
          <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Select Cloud Provider
          </label>

          <div
            onClick={() => setSelectedProvider("google_drive")}
            className={`flex items-center justify-between p-3.5 rounded-xl border transition-all cursor-pointer ${
              selectedProvider === "google_drive"
                ? "border-primary bg-primary/5 ring-1 ring-primary/40 shadow-sm"
                : "border-border hover:bg-muted/50"
            }`}
          >
            <div className="flex items-center gap-3">
              {/* Google Drive Logo SVG */}
              <div className="w-9 h-9 rounded-lg bg-white p-1.5 flex items-center justify-center shadow-xs">
                <svg className="w-full h-full" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">
                  <path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
                  <path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44c-.8 1.4-1.2 2.95-1.2 4.5h27.5z" fill="#00ac47"/>
                  <path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z" fill="#ea4335"/>
                  <path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.25z" fill="#00832d"/>
                  <path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.25z" fill="#2684fc"/>
                  <path d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/>
                </svg>
              </div>
              <div>
                <h4 className="font-semibold text-sm">Google Drive</h4>
                <p className="text-xs text-muted-foreground">Full drive browsing & zero-disk streaming</p>
              </div>
            </div>
            {selectedProvider === "google_drive" && (
              <CheckCircle2 className="w-5 h-5 text-primary" />
            )}
          </div>

          {/* Coming Soon Providers */}
          <div className="grid grid-cols-3 gap-2 opacity-55">
            <div className="p-2.5 rounded-lg border border-border/60 text-center text-xs">
              <span className="font-medium block">OneDrive</span>
              <span className="text-[10px] text-muted-foreground">Soon</span>
            </div>
            <div className="p-2.5 rounded-lg border border-border/60 text-center text-xs">
              <span className="font-medium block">MEGA</span>
              <span className="text-[10px] text-muted-foreground">Soon</span>
            </div>
            <div className="p-2.5 rounded-lg border border-border/60 text-center text-xs">
              <span className="font-medium block">Dropbox</span>
              <span className="text-[10px] text-muted-foreground">Soon</span>
            </div>
          </div>

          {/* Collapsible Custom Credentials */}
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground font-medium transition-colors cursor-pointer"
            >
              <span>Custom Google Client Credentials (Optional)</span>
              {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>

            {showAdvanced && (
              <div className="mt-3 p-3.5 rounded-lg bg-muted/40 border border-border/60 space-y-3 animate-in fade-in-50">
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Leave empty to use server default credentials configured in <code>.env</code>. You can provide your own personal Google Cloud Client ID if you prefer dedicated API quotas.
                </p>
                <div>
                  <Label htmlFor="clientId" className="text-xs font-medium">Google Client ID</Label>
                  <Input
                    id="clientId"
                    type="text"
                    placeholder="e.g. 123456...apps.googleusercontent.com"
                    value={customClientId}
                    onChange={(e) => setCustomClientId(e.target.value)}
                    className="h-8 text-xs mt-1"
                  />
                </div>
                <div>
                  <Label htmlFor="clientSecret" className="text-xs font-medium">Google Client Secret</Label>
                  <Input
                    id="clientSecret"
                    type="password"
                    placeholder="e.g. GOCSPX-..."
                    value={customClientSecret}
                    onChange={(e) => setCustomClientSecret(e.target.value)}
                    className="h-8 text-xs mt-1"
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="mt-2 flex-col sm:flex-row gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={isConnecting}
          >
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={handleConnectGoogle}
            disabled={isConnecting}
            className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90 font-medium"
          >
            {isConnecting ? (
              <span>Connecting...</span>
            ) : (
              <>
                <ExternalLink className="w-4 h-4" />
                <span>Connect with Google</span>
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
